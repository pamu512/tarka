"""Tenant overlay names for event_type (seed ∪ env ∪ overlay)."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from decision_api.models import EventTypeRow
from tarka_shared.ingest_contract_v1 import (
    load_registry_event_types,
    validate_event_type_shape,
)

log = logging.getLogger(__name__)
_seed_load_logged = False


def _seed_path() -> Path:
    return Path(__file__).resolve().parent / "data" / "event_types_v1.json"


def load_seed_event_types() -> frozenset[str]:
    """Registry allow-list (shared-core JSON ∪ local copy). Not an engine enum."""
    return load_registry_event_types() | _load_local_event_types()


def _load_local_event_types() -> frozenset[str]:
    global _seed_load_logged
    path = _seed_path()
    if not path.is_file():
        return frozenset()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        if not _seed_load_logged:
            log.warning("event type seed file invalid: %s (%s)", path, exc)
            _seed_load_logged = True
        return frozenset()
    if not isinstance(raw, list):
        return frozenset()
    names: set[str] = set()
    for item in raw:
        try:
            names.add(validate_event_type_shape(item))
        except ValueError:
            continue
    return frozenset(names)


async def list_names(session: AsyncSession, tenant_id: str) -> list[str]:
    result = await session.execute(
        select(EventTypeRow.name).where(EventTypeRow.tenant_id == tenant_id)
    )
    return [row[0] for row in result.all()]


async def load_names_or_empty(session, tenant_id: str) -> frozenset[str]:
    """Overlay names. On any error return empty so evaluate does not fail."""
    try:
        return frozenset(await list_names(session, tenant_id))
    except Exception:
        log.exception("event_types_load_failed tenant_id=%s", tenant_id)
        return frozenset()


async def upsert_name(
    session: AsyncSession, tenant_id: str, name: str
) -> EventTypeRow | None:
    """Insert overlay name. Seed names are already allowed — return None (no-op)."""
    name = validate_event_type_shape(name)
    if name in load_seed_event_types():
        return None
    result = await session.execute(
        select(EventTypeRow).where(
            EventTypeRow.tenant_id == tenant_id,
            EventTypeRow.name == name,
        )
    )
    existing = result.scalar_one_or_none()
    if existing is not None:
        return existing
    row = EventTypeRow(tenant_id=tenant_id, name=name)
    session.add(row)
    await session.flush()
    return row
