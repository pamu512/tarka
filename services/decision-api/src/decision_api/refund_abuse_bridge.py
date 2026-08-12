"""Evaluate → refund-abuse-risk sibling bridge (advisory refund_effect).

Downstream owns money movement unless tenant opts into host-action refund_hold.
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any, Callable

import httpx

log = logging.getLogger("decision-api.refund_abuse_bridge")

REFUND_CHECKPOINTS = frozenset({"refund", "return", "chargeback"})

# ponytail: process-local circuit; ceiling = multi-replica inconsistency — upgrade to Redis.
_CIRCUIT_FAILURES = 0
_CIRCUIT_OPEN_UNTIL = 0.0
DEFAULT_TIMEOUT_SECONDS = 2.0
DEFAULT_FAILURE_THRESHOLD = 3
DEFAULT_RECOVERY_SECONDS = 30.0


def reset_refund_circuit_for_tests() -> None:
    global _CIRCUIT_FAILURES, _CIRCUIT_OPEN_UNTIL
    _CIRCUIT_FAILURES = 0
    _CIRCUIT_OPEN_UNTIL = 0.0


def refund_circuit_open(
    *,
    failure_threshold: int = DEFAULT_FAILURE_THRESHOLD,
    recovery_seconds: float = DEFAULT_RECOVERY_SECONDS,
    now: float | None = None,
) -> bool:
    global _CIRCUIT_FAILURES, _CIRCUIT_OPEN_UNTIL
    t = time.monotonic() if now is None else now
    if _CIRCUIT_OPEN_UNTIL > t:
        return True
    if _CIRCUIT_OPEN_UNTIL and t >= _CIRCUIT_OPEN_UNTIL:
        _CIRCUIT_FAILURES = 0
        _CIRCUIT_OPEN_UNTIL = 0.0
    return False


def _record_success() -> None:
    global _CIRCUIT_FAILURES, _CIRCUIT_OPEN_UNTIL
    _CIRCUIT_FAILURES = 0
    _CIRCUIT_OPEN_UNTIL = 0.0


def _record_failure(
    *,
    failure_threshold: int = DEFAULT_FAILURE_THRESHOLD,
    recovery_seconds: float = DEFAULT_RECOVERY_SECONDS,
) -> None:
    global _CIRCUIT_FAILURES, _CIRCUIT_OPEN_UNTIL
    _CIRCUIT_FAILURES += 1
    if _CIRCUIT_FAILURES >= max(1, failure_threshold):
        _CIRCUIT_OPEN_UNTIL = time.monotonic() + max(0.1, recovery_seconds)


@dataclass(frozen=True)
class RefundBridgeResult:
    tags: list[str] = field(default_factory=list)
    refund_effect: str | None = None
    abuse_score: float | None = None
    fraud_score: float | None = None
    skipped_reason: str | None = None
    reason_codes: list[str] = field(default_factory=list)

    def evidence(self) -> dict[str, Any] | None:
        if self.skipped_reason and not self.tags and self.refund_effect is None:
            return {
                "bridge": "refund_abuse",
                "skipped_reason": self.skipped_reason,
                "degraded": True,
            }
        if (
            not self.tags
            and self.refund_effect is None
            and self.abuse_score is None
            and self.skipped_reason is None
        ):
            return None
        return {
            "bridge": "refund_abuse",
            "refund_effect": self.refund_effect,
            "abuse_score": self.abuse_score,
            "fraud_score": self.fraud_score,
            "reason_codes": list(self.reason_codes),
            "tags": list(self.tags),
            "skipped_reason": self.skipped_reason,
            "advisory": True,
            "note": "Advisory by default — Downstream owns hold/release unless host-action enabled",
        }


def should_invoke_refund_bridge(
    *, metadata: dict[str, Any] | None, event_type: str | None = None
) -> bool:
    md = metadata if isinstance(metadata, dict) else {}
    cp = str(md.get("checkpoint") or "").strip().lower()
    et = str(event_type or md.get("event_type") or "").strip().lower()
    return cp in REFUND_CHECKPOINTS or et in REFUND_CHECKPOINTS


def bridge_config() -> dict[str, Any]:
    url = (
        os.environ.get("REFUND_ABUSE_URL")
        or os.environ.get("TARKA_REFUND_ABUSE_URL")
        or ""
    ).strip()
    key = (
        os.environ.get("REFUND_ABUSE_API_KEY")
        or os.environ.get("TARKA_REFUND_ABUSE_API_KEY")
        or ""
    ).strip()
    return {
        "url": url,
        "api_key": key,
        "configured": bool(url),
        "live_claim_allowed": bool(url and key),
        "blockers": (
            ([] if url else ["url_missing"])
            + ([] if key else ["api_key_missing"])
        ),
    }


def map_refund_response(payload: dict[str, Any]) -> RefundBridgeResult:
    tags: list[str] = []
    effect = payload.get("refund_effect") or payload.get("effect")
    abuse = payload.get("abuse_score")
    fraud = payload.get("fraud_score") or payload.get("score")
    reasons = payload.get("reason_codes") or payload.get("reasons") or []
    if not isinstance(reasons, list):
        reasons = [str(reasons)]
    if effect:
        tags.append(f"refund:effect:{effect}")
    try:
        abuse_f = float(abuse) if abuse is not None else None
    except (TypeError, ValueError):
        abuse_f = None
    try:
        fraud_f = float(fraud) if fraud is not None else None
    except (TypeError, ValueError):
        fraud_f = None
    if abuse_f is not None and abuse_f >= 0.7:
        tags.append("risk:refund_burst")
        tags.append("action:refund_step_up")
    if str(effect or "").lower() in ("hold", "refund_hold", "manual_review"):
        tags.append("action:refund_hold")
    return RefundBridgeResult(
        tags=list(dict.fromkeys(tags)),
        refund_effect=str(effect) if effect else None,
        abuse_score=abuse_f,
        fraud_score=fraud_f,
        reason_codes=[str(r) for r in reasons][:32],
    )


async def maybe_invoke_refund_abuse(
    *,
    http: httpx.AsyncClient | None,
    tenant_id: str,
    entity_id: str,
    metadata: dict[str, Any] | None,
    event_type: str = "",
    features: dict[str, Any] | None = None,
    metrics_inc: Callable[[str], None] | None = None,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
) -> RefundBridgeResult:
    if not should_invoke_refund_bridge(metadata=metadata, event_type=event_type):
        return RefundBridgeResult(skipped_reason="checkpoint_mismatch")
    cfg = bridge_config()
    if not cfg["url"]:
        return RefundBridgeResult(skipped_reason="bridge_unconfigured")
    if refund_circuit_open():
        if metrics_inc:
            metrics_inc("refund_abuse_bridge_circuit_open")
        return RefundBridgeResult(skipped_reason="circuit_open")
    if http is None:
        return RefundBridgeResult(skipped_reason="http_client_missing")
    url = f"{cfg['url'].rstrip('/')}/v1/evaluate"
    headers: dict[str, str] = {"Content-Type": "application/json"}
    if cfg["api_key"]:
        headers["Authorization"] = f"Bearer {cfg['api_key']}"
    body = {
        "tenant_id": tenant_id,
        "entity_id": entity_id,
        "type": "refund",
        "features": dict(features or {}),
        "metadata": dict(metadata or {}),
    }
    try:
        r = await http.post(url, json=body, headers=headers, timeout=timeout_seconds)
        if r.status_code >= 400:
            _record_failure()
            if metrics_inc:
                metrics_inc("refund_abuse_bridge_failed")
            return RefundBridgeResult(skipped_reason=f"upstream_http_{r.status_code}")
        data = r.json() if r.content else {}
        if not isinstance(data, dict):
            data = {}
        _record_success()
        return map_refund_response(data)
    except Exception:
        _record_failure()
        log.exception("refund_abuse_bridge_failed")
        if metrics_inc:
            metrics_inc("refund_abuse_bridge_failed")
        return RefundBridgeResult(skipped_reason="upstream_error")
