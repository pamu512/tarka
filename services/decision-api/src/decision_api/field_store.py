"""Tenant overlay + buyer-key maps for the field registry."""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from decision_api.models import FieldMap, FieldRegistryRow
from field_registry import SOURCES, seed_names, validate_registry_name

log = logging.getLogger(__name__)


class FieldRegistrySeedLocked(Exception):
    """Tenant overlay cannot overwrite a tarka_core seed name."""


class FieldRegistryUnknownName(Exception):
    """Map target is neither a seed name nor a tenant overlay row."""


def _require_explanation(explanation: str) -> str:
    stripped = explanation.strip()
    if not stripped or len(stripped) > 500:
        raise ValueError("explanation must be 1..500 characters")
    return stripped


def _require_source(source: str) -> str:
    if source not in SOURCES:
        raise ValueError(f"invalid source: {source!r}")
    return source


def _require_buyer_key(buyer_key: str) -> str:
    stripped = buyer_key.strip()
    if not stripped or len(stripped) > 256:
        raise ValueError("buyer_key must be non-empty and at most 256 characters")
    return stripped


async def list_overlay(session: AsyncSession, tenant_id: str) -> list[FieldRegistryRow]:
    result = await session.execute(
        select(FieldRegistryRow).where(FieldRegistryRow.tenant_id == tenant_id)
    )
    return list(result.scalars().all())


async def get_overlay(
    session: AsyncSession, tenant_id: str, name: str
) -> FieldRegistryRow | None:
    result = await session.execute(
        select(FieldRegistryRow).where(
            FieldRegistryRow.tenant_id == tenant_id,
            FieldRegistryRow.name == name,
        )
    )
    return result.scalar_one_or_none()


async def upsert_overlay(
    session: AsyncSession,
    tenant_id: str,
    name: str,
    explanation: str,
    source: str,
) -> FieldRegistryRow:
    name = validate_registry_name(name)
    if name in seed_names():
        raise FieldRegistrySeedLocked(name)
    explanation = _require_explanation(explanation)
    source = _require_source(source)
    existing = await get_overlay(session, tenant_id, name)
    if existing is not None:
        existing.explanation = explanation
        existing.source = source
        await session.flush()
        return existing
    row = FieldRegistryRow(
        tenant_id=tenant_id,
        name=name,
        explanation=explanation,
        source=source,
    )
    session.add(row)
    await session.flush()
    return row


async def list_maps(session: AsyncSession, tenant_id: str) -> list[FieldMap]:
    result = await session.execute(
        select(FieldMap).where(FieldMap.tenant_id == tenant_id)
    )
    return list(result.scalars().all())


async def load_maps_or_empty(session, tenant_id) -> list[tuple[str, str]]:
    """Load tenant maps. On any error return [] so evaluate does not fail."""
    try:
        rows = await list_maps(session, tenant_id)
        return [(row.buyer_key, row.registry_name) for row in rows]
    except Exception:
        log.exception("field_maps_load_failed tenant_id=%s", tenant_id)
        return []


async def upsert_map(
    session: AsyncSession,
    tenant_id: str,
    buyer_key: str,
    registry_name: str,
) -> FieldMap:
    buyer_key = _require_buyer_key(buyer_key)
    registry_name = registry_name.strip()
    if registry_name not in seed_names():
        if await get_overlay(session, tenant_id, registry_name) is None:
            raise FieldRegistryUnknownName(registry_name)
    result = await session.execute(
        select(FieldMap).where(
            FieldMap.tenant_id == tenant_id,
            FieldMap.buyer_key == buyer_key,
        )
    )
    existing = result.scalar_one_or_none()
    if existing is not None:
        existing.registry_name = registry_name
        await session.flush()
        return existing
    row = FieldMap(
        tenant_id=tenant_id,
        buyer_key=buyer_key,
        registry_name=registry_name,
    )
    session.add(row)
    await session.flush()
    return row
