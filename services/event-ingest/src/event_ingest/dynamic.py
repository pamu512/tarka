"""Schemaless ingest → contract v1 evaluate shape."""

from __future__ import annotations

from typing import Any

from .ingest_contract import VALID_EVENT_TYPES

_TENANT_KEYS = ("tenant_id", "tenantId")
_ENTITY_KEYS = ("entity_id", "entityId", "user_id", "userId", "customer_id", "customerId")
_TYPE_KEYS = ("event_type", "eventType", "type")
_SKIP = frozenset(_TENANT_KEYS + _ENTITY_KEYS + _TYPE_KEYS + ("metadata", "payload"))


def _first_str(body: dict[str, Any], keys: tuple[str, ...]) -> str | None:
    for key in keys:
        raw = body.get(key)
        if isinstance(raw, str) and raw.strip():
            return raw.strip()
    return None


def heuristic_map_to_evaluate_request(body: dict[str, Any]) -> dict[str, Any] | None:
    tenant = _first_str(body, _TENANT_KEYS)
    entity = _first_str(body, _ENTITY_KEYS)
    event_type = _first_str(body, _TYPE_KEYS)
    if not tenant or not entity or not event_type:
        return None
    payload = body.get("payload")
    if not isinstance(payload, dict):
        payload = {k: v for k, v in body.items() if k not in _SKIP}
    meta = body.get("metadata") if isinstance(body.get("metadata"), dict) else {}
    if event_type not in VALID_EVENT_TYPES:
        return None
    return {
        "tenant_id": tenant,
        "entity_id": entity,
        "event_type": event_type,
        "payload": payload,
        "metadata": meta,
    }
