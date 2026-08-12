"""Evaluate → offline-cancel-risk sibling bridge (cancel / GPS leakage heads)."""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any, Callable

import httpx

log = logging.getLogger("decision-api.offline_cancel_bridge")

CANCEL_CHECKPOINTS = frozenset({"cancel", "reassign", "offline_complete"})

# ponytail: process-local circuit; ceiling = multi-replica inconsistency — upgrade to Redis.
_CIRCUIT_FAILURES = 0
_CIRCUIT_OPEN_UNTIL = 0.0
DEFAULT_TIMEOUT_SECONDS = 2.0
DEFAULT_FAILURE_THRESHOLD = 3
DEFAULT_RECOVERY_SECONDS = 30.0


def reset_cancel_circuit_for_tests() -> None:
    global _CIRCUIT_FAILURES, _CIRCUIT_OPEN_UNTIL
    _CIRCUIT_FAILURES = 0
    _CIRCUIT_OPEN_UNTIL = 0.0


def cancel_circuit_open(
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
class CancelBridgeResult:
    tags: list[str] = field(default_factory=list)
    heads: dict[str, float] = field(default_factory=dict)
    skipped_reason: str | None = None

    def evidence(self) -> dict[str, Any] | None:
        if self.skipped_reason and not self.tags and not self.heads:
            return {
                "bridge": "offline_cancel",
                "skipped_reason": self.skipped_reason,
                "degraded": True,
            }
        if not self.tags and not self.heads and self.skipped_reason is None:
            return None
        return {
            "bridge": "offline_cancel",
            "heads": dict(self.heads),
            "tags": list(self.tags),
            "skipped_reason": self.skipped_reason,
        }


def should_invoke_cancel_bridge(
    *, metadata: dict[str, Any] | None, event_type: str | None = None
) -> bool:
    md = metadata if isinstance(metadata, dict) else {}
    cp = str(md.get("checkpoint") or "").strip().lower()
    et = str(event_type or md.get("event_type") or "").strip().lower()
    return cp in CANCEL_CHECKPOINTS or et in CANCEL_CHECKPOINTS


def bridge_config() -> dict[str, Any]:
    url = (
        os.environ.get("OFFLINE_CANCEL_URL")
        or os.environ.get("TARKA_OFFLINE_CANCEL_URL")
        or ""
    ).strip()
    key = (
        os.environ.get("OFFLINE_CANCEL_API_KEY")
        or os.environ.get("TARKA_OFFLINE_CANCEL_API_KEY")
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


def map_cancel_response(payload: dict[str, Any]) -> CancelBridgeResult:
    tags: list[str] = []
    heads_raw = payload.get("heads") or payload.get("scores") or {}
    heads: dict[str, float] = {}
    if isinstance(heads_raw, dict):
        for k, v in heads_raw.items():
            try:
                heads[str(k)] = float(v)
            except (TypeError, ValueError):
                continue
    # Common head names from offline-cancel-risk toolkit
    for head, tag in (
        ("cancelled_offline", "risk:courier_spoof"),
        ("cancel_abuse", "risk:refund_burst"),
        ("selective_theft", "risk:cod_abuse"),
    ):
        score = heads.get(head)
        if score is not None and score >= 0.55:
            tags.append(tag)
            tags.append(f"cancel:head:{head}")
    return CancelBridgeResult(tags=list(dict.fromkeys(tags)), heads=heads)


async def maybe_invoke_offline_cancel(
    *,
    http: httpx.AsyncClient | None,
    tenant_id: str,
    entity_id: str,
    metadata: dict[str, Any] | None,
    event_type: str = "",
    features: dict[str, Any] | None = None,
    metrics_inc: Callable[[str], None] | None = None,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
) -> CancelBridgeResult:
    if not should_invoke_cancel_bridge(metadata=metadata, event_type=event_type):
        return CancelBridgeResult(skipped_reason="checkpoint_mismatch")
    cfg = bridge_config()
    if not cfg["url"]:
        return CancelBridgeResult(skipped_reason="bridge_unconfigured")
    if cancel_circuit_open():
        if metrics_inc:
            metrics_inc("offline_cancel_bridge_circuit_open")
        return CancelBridgeResult(skipped_reason="circuit_open")
    if http is None:
        return CancelBridgeResult(skipped_reason="http_client_missing")
    url = f"{cfg['url'].rstrip('/')}/v1/evaluate"
    headers: dict[str, str] = {"Content-Type": "application/json"}
    if cfg["api_key"]:
        headers["Authorization"] = f"Bearer {cfg['api_key']}"
    body = {
        "tenant_id": tenant_id,
        "entity_id": entity_id,
        "type": "cancel",
        "features": dict(features or {}),
        "metadata": dict(metadata or {}),
    }
    try:
        r = await http.post(url, json=body, headers=headers, timeout=timeout_seconds)
        if r.status_code >= 400:
            _record_failure()
            if metrics_inc:
                metrics_inc("offline_cancel_bridge_failed")
            return CancelBridgeResult(skipped_reason=f"upstream_http_{r.status_code}")
        data = r.json() if r.content else {}
        if not isinstance(data, dict):
            data = {}
        _record_success()
        return map_cancel_response(data)
    except Exception:
        _record_failure()
        log.exception("offline_cancel_bridge_failed")
        if metrics_inc:
            metrics_inc("offline_cancel_bridge_failed")
        return CancelBridgeResult(skipped_reason="upstream_error")
