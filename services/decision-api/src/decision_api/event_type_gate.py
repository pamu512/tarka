"""Evaluate allow-list for event_type: seed ∪ env ∪ tenant overlay."""

from __future__ import annotations

import logging
import os

from fastapi import HTTPException

from tarka_shared.ingest_contract_v1 import parse_env_event_types

log = logging.getLogger(__name__)
_overlay_fail_logged = False


def event_type_allow_list(overlay: frozenset[str] | None = None) -> frozenset[str]:
    from decision_api.event_type_store import load_seed_event_types

    return (
        load_seed_event_types()
        | frozenset(overlay or ())
        | parse_env_event_types(os.environ.get("TARKA_EVENT_TYPES"))
    )


def raise_if_event_type_not_allowed(
    name: str, *, overlay: frozenset[str] | None = None
) -> str:
    if name not in event_type_allow_list(overlay):
        raise HTTPException(
            status_code=422,
            detail={
                "error": "ingest_contract_violation",
                "reason_codes": ["ingest_event_type_invalid"],
                "message": f"event_type {name!r} is not on the allow-list",
            },
        )
    return name


async def load_event_type_overlay_or_empty(session, tenant_id: str) -> frozenset[str]:
    """Overlay names. Store down → empty (seed ∪ env still apply). Log once."""
    global _overlay_fail_logged
    try:
        from decision_api.event_type_store import load_names_or_empty

        return await load_names_or_empty(session, tenant_id)
    except Exception:
        if not _overlay_fail_logged:
            log.warning("event_types overlay unavailable; using seed ∪ env")
            _overlay_fail_logged = True
        return frozenset()


async def require_allowed_event_type(session, tenant_id: str, name: str) -> str:
    overlay = await load_event_type_overlay_or_empty(session, tenant_id)
    return raise_if_event_type_not_allowed(name, overlay=overlay)
