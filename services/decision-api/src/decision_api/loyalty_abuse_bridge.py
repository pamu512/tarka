"""Evaluate → loyalty-abuse redeem bridge (Marketplace B2)."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

log = logging.getLogger("decision-api.loyalty_abuse_bridge")

REDEEM_CHECKPOINTS = frozenset({"redeem"})


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


def map_loyalty_response(response: dict[str, Any]) -> list[str]:
    """Map loyalty-abuse Decision friction to Tarka tag vocabulary."""
    if not isinstance(response, dict):
        return []
    friction = response.get("friction")
    tags = friction_to_tags(friction if isinstance(friction, str) else None)
    score = response.get("score")
    if tags and score is not None:
        log.info(
            "loyalty_abuse_bridge friction=%s score=%s tags=%s",
            friction,
            score,
            tags,
        )
    return tags


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
) -> list[str]:
    url_base = (base_url or "").strip()
    secret = (api_key or "").strip()
    if not url_base or not secret:
        return []
    try:
        r = await http.post(
            f"{url_base.rstrip('/')}/v1/evaluate",
            json=body,
            headers={"Authorization": f"Bearer {secret}"},
            timeout=2.0,
        )
        r.raise_for_status()
        data = r.json()
        if not isinstance(data, dict):
            return []
        return map_loyalty_response(data)
    except Exception:
        log.exception("loyalty_abuse_bridge_failed")
        if callable(metrics_inc):
            metrics_inc("loyalty_abuse_bridge_failed")
        return []


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
) -> list[str]:
    if not should_call_loyalty_abuse(metadata=metadata, event_type=event_type):
        return []
    body = build_loyalty_event(
        tenant_id=tenant_id,
        entity_id=entity_id,
        trace_id=trace_id,
        payload=payload,
        metadata=metadata,
    )
    return await maybe_call_loyalty_abuse(
        http=http,
        base_url=loyalty_abuse_url,
        api_key=loyalty_abuse_api_key,
        body=body,
        metrics_inc=metrics_inc,
    )
