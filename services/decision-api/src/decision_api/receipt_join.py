"""Copy label-join-v1 keys onto evaluate snapshots. Never invent party ids."""

from __future__ import annotations

from typing import Any

OPTIONAL_PARTY_KEYS = (
    "order_id",
    "promo_id",
    "courier_id",
    "merchant_id",
    "payment_instrument_id",
    "device_id",
)


def join_keys_from_event(
    *,
    trace_id: str,
    tenant_id: str,
    entity_id: str,
    payload: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    tid = str(trace_id or "").strip()
    tenant = str(tenant_id or "").strip()
    entity = str(entity_id or "").strip()
    if not tid or not tenant or not entity:
        raise ValueError(
            "evaluation_token/trace_id, tenant_id, and entity_id are required"
        )
    out: dict[str, Any] = {
        "evaluation_token": tid,
        "trace_id": tid,
        "tenant_id": tenant,
        "entity_id": entity,
    }
    sources = [src for src in (payload, metadata) if isinstance(src, dict)]
    for key in OPTIONAL_PARTY_KEYS:
        for src in sources:
            raw = src.get(key)
            if raw is None:
                continue
            text = str(raw).strip()
            if text:
                out[key] = text
                break
    return out
