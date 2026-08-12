"""Evaluate → loyalty-abuse redeem bridge (Marketplace B2)."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

log = logging.getLogger("decision-api.loyalty_abuse_bridge")

REDEEM_CHECKPOINTS = frozenset({"redeem"})

# ponytail: process-local circuit; ceiling = multi-replica inconsistency — upgrade to shared Redis circuit.
_CIRCUIT_FAILURES = 0
_CIRCUIT_OPEN_UNTIL = 0.0
DEFAULT_TIMEOUT_SECONDS = 2.0
DEFAULT_FAILURE_THRESHOLD = 3
DEFAULT_RECOVERY_SECONDS = 30.0


def reset_loyalty_circuit_for_tests() -> None:
    global _CIRCUIT_FAILURES, _CIRCUIT_OPEN_UNTIL
    _CIRCUIT_FAILURES = 0
    _CIRCUIT_OPEN_UNTIL = 0.0


def loyalty_circuit_open(
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


def _record_loyalty_success() -> None:
    global _CIRCUIT_FAILURES, _CIRCUIT_OPEN_UNTIL
    _CIRCUIT_FAILURES = 0
    _CIRCUIT_OPEN_UNTIL = 0.0


def _record_loyalty_failure(
    *,
    failure_threshold: int = DEFAULT_FAILURE_THRESHOLD,
    recovery_seconds: float = DEFAULT_RECOVERY_SECONDS,
) -> None:
    global _CIRCUIT_FAILURES, _CIRCUIT_OPEN_UNTIL
    _CIRCUIT_FAILURES += 1
    if _CIRCUIT_FAILURES >= max(1, failure_threshold):
        _CIRCUIT_OPEN_UNTIL = time.monotonic() + max(0.1, recovery_seconds)


@dataclass(frozen=True)
class LoyaltyBridgeResult:
    """Tags + optional evidence for evaluate audit / response merge."""

    tags: list[str] = field(default_factory=list)
    friction: str | None = None
    score: float | None = None
    skipped_reason: str | None = None
    feed_gate: dict[str, Any] | None = None
    economics_status: str | None = None

    def evidence(self) -> dict[str, Any] | None:
        if (
            not self.tags
            and self.friction is None
            and self.score is None
            and self.skipped_reason is None
            and self.feed_gate is None
            and self.economics_status is None
        ):
            return None
        out: dict[str, Any] = {"source": "loyalty_abuse_bridge"}
        if self.friction is not None:
            out["friction"] = self.friction
        if self.score is not None:
            out["score"] = self.score
        if self.tags:
            out["tags"] = list(self.tags)
        if self.skipped_reason is not None:
            out["skipped_reason"] = self.skipped_reason
        if self.feed_gate is not None:
            out["feed_gate"] = self.feed_gate
        if self.economics_status is not None:
            out["economics_status"] = self.economics_status
        return out


def should_call_loyalty_abuse(
    *,
    metadata: dict[str, Any] | None,
    event_type: str | None = None,
) -> bool:
    meta = metadata if isinstance(metadata, dict) else {}
    checkpoint = str(meta.get("checkpoint") or "").strip().lower()
    et = str(event_type or "").strip().lower()
    return checkpoint in REDEEM_CHECKPOINTS or et in REDEEM_CHECKPOINTS


def friction_to_tags(friction: str | None) -> list[str]:
    f = str(friction or "allow").strip().lower()
    if not f or f == "allow":
        return []
    return [f"loyalty:friction:{f}"]


def map_loyalty_response(
    response: dict[str, Any],
    *,
    feed_gate: dict[str, Any] | None = None,
) -> LoyaltyBridgeResult:
    """Map loyalty-abuse Decision friction to Tarka tag vocabulary + evidence."""
    if not isinstance(response, dict):
        return LoyaltyBridgeResult()
    friction_raw = response.get("friction")
    # UnifiedDecision nests friction as an object; plain Decision uses string.
    if isinstance(friction_raw, dict):
        friction_raw = friction_raw.get("friction") or friction_raw.get("action")
    friction = friction_raw.strip().lower() if isinstance(friction_raw, str) else None
    tags = friction_to_tags(friction)
    score_raw = response.get("score")
    if score_raw is None and isinstance(response.get("friction"), dict):
        score_raw = response["friction"].get("score")
    score: float | None = None
    if isinstance(score_raw, (int, float)):
        score = float(score_raw)

    from decision_api.loyalty_feed_posture import (
        economics_feed_status,
        parse_economics_block,
        tags_for_feed_status,
    )

    eco = parse_economics_block(response)
    if eco:
        tags = list(
            dict.fromkeys(tags + tags_for_feed_status(economics_feed_status(eco)))
        )
    elif isinstance(feed_gate, dict) and feed_gate.get("status"):
        tags = list(
            dict.fromkeys(tags + tags_for_feed_status(str(feed_gate["status"])))
        )

    if tags:
        log.info(
            "loyalty_abuse_bridge friction=%s score=%s tags=%s",
            friction,
            score,
            tags,
        )
    from decision_api.loyalty_feed_posture import economics_feed_status

    eco_status = economics_feed_status(eco) if eco else None
    return LoyaltyBridgeResult(
        tags=tags,
        friction=friction,
        score=score,
        feed_gate=feed_gate if isinstance(feed_gate, dict) else None,
        economics_status=eco_status,
    )


def build_loyalty_event(
    *,
    tenant_id: str,
    entity_id: str,
    trace_id: str,
    payload: dict[str, Any] | None,
    metadata: dict[str, Any] | None,
) -> dict[str, Any]:
    """Build POST /v1/evaluate body with loyalty-abuse EventEnvelope."""
    meta = metadata if isinstance(metadata, dict) else {}
    pl = payload if isinstance(payload, dict) else {}
    ts_raw = meta.get("event_time") or pl.get("event_time")
    if isinstance(ts_raw, str) and ts_raw.strip():
        ts = ts_raw.strip()
    else:
        ts = datetime.now(timezone.utc).isoformat()
    session_id = str(meta.get("session_id") or pl.get("session_id") or trace_id)
    device_id = str(meta.get("device_id") or pl.get("device_id") or "unknown")
    ip = str(
        meta.get("ip")
        or pl.get("ip")
        or meta.get("ip_address")
        or pl.get("ip_address")
        or "0.0.0.0"
    )
    event: dict[str, Any] = {
        "event_id": trace_id,
        "tenant_id": tenant_id,
        "ts": ts,
        "type": "redeem",
        "account_id": entity_id,
        "session_id": session_id,
        "device_id": device_id,
        "ip": ip,
        "payload": dict(pl),
    }
    for optional in ("email", "phone", "payment_instrument_hash"):
        val = meta.get(optional) or pl.get(optional)
        if isinstance(val, str) and val.strip():
            event[optional] = val.strip()
    return {"event": event}


async def maybe_call_loyalty_abuse(
    *,
    http: Any,
    base_url: str,
    api_key: str,
    body: dict[str, Any],
    metrics_inc: Any = None,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    failure_threshold: int = DEFAULT_FAILURE_THRESHOLD,
    recovery_seconds: float = DEFAULT_RECOVERY_SECONDS,
) -> LoyaltyBridgeResult:
    url_base = (base_url or "").strip()
    secret = (api_key or "").strip()
    if not url_base or not secret:
        return LoyaltyBridgeResult()
    if loyalty_circuit_open(
        failure_threshold=failure_threshold, recovery_seconds=recovery_seconds
    ):
        if callable(metrics_inc):
            metrics_inc("loyalty_abuse_bridge_circuit_open")
        return LoyaltyBridgeResult(
            tags=["enrichment:loyalty_circuit_open"],
            skipped_reason="circuit_open",
        )
    try:
        r = await http.post(
            f"{url_base.rstrip('/')}/v1/evaluate",
            json=body,
            headers={"Authorization": f"Bearer {secret}"},
            timeout=float(timeout_seconds),
        )
        r.raise_for_status()
        data = r.json()
        if not isinstance(data, dict):
            _record_loyalty_failure(
                failure_threshold=failure_threshold, recovery_seconds=recovery_seconds
            )
            return LoyaltyBridgeResult(skipped_reason="invalid_response")
        _record_loyalty_success()
        return map_loyalty_response(data, feed_gate=None)
    except Exception:
        log.exception("loyalty_abuse_bridge_failed")
        _record_loyalty_failure(
            failure_threshold=failure_threshold, recovery_seconds=recovery_seconds
        )
        if callable(metrics_inc):
            metrics_inc("loyalty_abuse_bridge_failed")
        return LoyaltyBridgeResult(
            tags=["enrichment:loyalty_bridge_failed"],
            skipped_reason="call_failed",
        )


async def maybe_call_loyalty_abuse_from_evaluate(
    *,
    http: Any,
    loyalty_abuse_url: str,
    loyalty_abuse_api_key: str,
    tenant_id: str,
    entity_id: str,
    trace_id: str,
    payload: dict[str, Any] | None,
    metadata: dict[str, Any] | None,
    event_type: str = "",
    metrics_inc: Any = None,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    failure_threshold: int = DEFAULT_FAILURE_THRESHOLD,
    recovery_seconds: float = DEFAULT_RECOVERY_SECONDS,
) -> LoyaltyBridgeResult:
    if not should_call_loyalty_abuse(metadata=metadata, event_type=event_type):
        return LoyaltyBridgeResult()

    from decision_api.loyalty_feed_posture import (
        extract_feed_snapshot,
        tags_for_feed_status,
        validate_feed_snapshot,
    )

    feed_gate = validate_feed_snapshot(
        extract_feed_snapshot(metadata=metadata, payload=payload)
    )
    body = build_loyalty_event(
        tenant_id=tenant_id,
        entity_id=entity_id,
        trace_id=trace_id,
        payload=payload,
        metadata=metadata,
    )
    # Pass through snapshot when present so loyalty-abuse /v1/decide can use it later;
    # evaluate path ignores unknown keys safely if wrapped under event.payload.
    snap = extract_feed_snapshot(metadata=metadata, payload=payload)
    if isinstance(snap, dict) and isinstance(body.get("event"), dict):
        body["event"].setdefault("payload", {})
        if isinstance(body["event"]["payload"], dict):
            body["event"]["payload"]["feed_snapshot"] = snap
        body["feed_snapshot"] = snap

    result = await maybe_call_loyalty_abuse(
        http=http,
        base_url=loyalty_abuse_url,
        api_key=loyalty_abuse_api_key,
        body=body,
        metrics_inc=metrics_inc,
        timeout_seconds=timeout_seconds,
        failure_threshold=failure_threshold,
        recovery_seconds=recovery_seconds,
    )
    # Re-map with feed_gate when response had no economics (typical /v1/evaluate).
    if result.economics_status is None and result.feed_gate is None:
        extra = tags_for_feed_status(str(feed_gate.get("status") or "unknown"))
        merged = list(dict.fromkeys(list(result.tags) + extra))
        return LoyaltyBridgeResult(
            tags=merged,
            friction=result.friction,
            score=result.score,
            skipped_reason=result.skipped_reason,
            feed_gate=feed_gate,
            economics_status=None,
        )
    if result.feed_gate is None:
        return LoyaltyBridgeResult(
            tags=result.tags,
            friction=result.friction,
            score=result.score,
            skipped_reason=result.skipped_reason,
            feed_gate=feed_gate,
            economics_status=result.economics_status,
        )
    return result
