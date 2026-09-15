"""Schemaless ingest → contract v1 evaluate shape."""

from __future__ import annotations

import os
from typing import Any

from tarka_shared.ingest_contract_v1 import allowed_event_types, parse_env_event_types

_TENANT_KEYS = ("tenant_id", "tenantId")
_ENTITY_KEYS = ("entity_id", "entityId", "user_id", "userId", "customer_id", "customerId")
_TYPE_KEYS = ("event_type", "eventType", "type")
_ROLE_KEYS = ("role", "party_role")
_SKIP = frozenset(_TENANT_KEYS + _ENTITY_KEYS + _TYPE_KEYS + _ROLE_KEYS + ("metadata", "payload"))


def _first_str(body: dict[str, Any], keys: tuple[str, ...]) -> str | None:
    for key in keys:
        raw = body.get(key)
        if isinstance(raw, str) and raw.strip():
            return raw.strip()
    return None


def heuristic_candidates_present(body: dict[str, Any]) -> bool:
    """True when tenant/entity/event_type are all present (mapping can only fail on allow-list)."""
    return bool(
        _first_str(body, _TENANT_KEYS)
        and _first_str(body, _ENTITY_KEYS)
        and _first_str(body, _TYPE_KEYS)
    )


def heuristic_map_to_evaluate_request(
    body: dict[str, Any],
    extra_allowed: frozenset[str] | None = None,
) -> dict[str, Any] | None:
    tenant = _first_str(body, _TENANT_KEYS)
    entity = _first_str(body, _ENTITY_KEYS)
    event_type = _first_str(body, _TYPE_KEYS)
    if not tenant or not entity or not event_type:
        return None
    payload = body.get("payload")
    if not isinstance(payload, dict):
        payload = {k: v for k, v in body.items() if k not in _SKIP}
    meta = body.get("metadata") if isinstance(body.get("metadata"), dict) else {}
    allowed = allowed_event_types(
        extra_allowed,
        parse_env_event_types(os.environ.get("TARKA_EVENT_TYPES")),
    )
    if event_type not in allowed:
        return None
    return {
        "tenant_id": tenant,
        "entity_id": entity,
        "event_type": event_type,
        # EvaluateRequest.role is required; unknown producers omit it. "member"
        # matches the canonical smoke/quickstart party role.
        "role": _first_str(body, _ROLE_KEYS) or "member",
        "payload": payload,
        "metadata": meta,
    }
