"""Shared-device index: Postgres side-table for entity-risk device lookups.

Replaces the per-entity tenant-wide OPTIONAL MATCH scan in entity_risk_sql
(O(N) per compute, O(N^2) per refresh) with an indexed (tenant_id, device_id)
lookup. Same pattern as search_keys: maintained fail-soft on entity upsert,
swept on delete, tolerated-missing on read.
"""

from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger("graph-service.device_index")

_ENSURED = False

_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS entity_device_index (
    tenant_id TEXT NOT NULL,
    device_id TEXT NOT NULL,
    external_id TEXT NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, device_id, external_id)
)
"""

_INDEX_SQL = (
    "CREATE INDEX IF NOT EXISTS ix_device_index_tenant_device "
    "ON entity_device_index (tenant_id, device_id)"
)


async def _acquire() -> Any:
    from .search_keys import _acquire as _sk_acquire

    return await _sk_acquire()


async def ensure_device_index_table() -> None:
    global _ENSURED
    if _ENSURED:
        return
    pool = await _acquire()
    async with pool.acquire() as conn:
        await conn.execute(_TABLE_SQL)
        await conn.execute(_INDEX_SQL)
    _ENSURED = True


async def upsert_device_index(tenant_id: str, device_id: str | None, external_id: str) -> None:
    """One row per (tenant, device, entity). No device → no row."""
    dev = (device_id or "").strip()
    if not dev:
        return
    await ensure_device_index_table()
    pool = await _acquire()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO entity_device_index (tenant_id, device_id, external_id, updated_at)
            VALUES ($1, $2, $3, now())
            ON CONFLICT (tenant_id, device_id, external_id)
            DO UPDATE SET updated_at = now()
            """,
            tenant_id,
            dev,
            external_id,
        )


async def delete_device_index(tenant_id: str, external_id: str) -> None:
    """Sweep every device row for a deleted entity (any device it held)."""
    try:
        await ensure_device_index_table()
    except Exception:
        log.warning("device_index_ensure_failed tenant=%s", tenant_id, exc_info=True)
        return
    pool = await _acquire()
    async with pool.acquire() as conn:
        await conn.execute(
            "DELETE FROM entity_device_index WHERE tenant_id = $1 AND external_id = $2",
            tenant_id,
            external_id,
        )


async def count_shared_device(tenant_id: str, device_id: str | None, external_id: str) -> int:
    """Other entities on the same device (self excluded). Empty device → 0."""
    dev = (device_id or "").strip()
    if not dev:
        return 0
    try:
        await ensure_device_index_table()
        pool = await _acquire()
    except Exception:
        log.warning("device_index_unavailable tenant=%s", tenant_id, exc_info=True)
        return 0
    async with pool.acquire() as conn:
        n = await conn.fetchval(
            """
            SELECT count(*) FROM entity_device_index
            WHERE tenant_id = $1 AND device_id = $2 AND external_id <> $3
            """,
            tenant_id,
            dev,
            external_id,
        )
    return int(n or 0)


async def backfill_tenant_device_index(tenant_id: str) -> int:
    """Bulk-load the index for a pre-existing tenant (one INSERT..SELECT per tenant,
    not per entity). Returns rowcount-ish 0; failures propagate to the caller."""
    await ensure_device_index_table()
    pool = await _acquire()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO entity_device_index (tenant_id, device_id, external_id, updated_at)
            SELECT $1, dev, eid, now()
            FROM ag_catalog.cypher('tarka'::name, $$
                MATCH (n)
                WHERE n.tenant_id = $tenant_id AND n.device_id IS NOT NULL
                RETURN n.external_id AS eid, n.device_id AS dev
            $$::cstring, $2::ag_catalog.agtype)
            AS (eid ag_catalog.agtype, dev ag_catalog.agtype)
            ON CONFLICT (tenant_id, device_id, external_id) DO UPDATE SET updated_at = now()
            """,
            tenant_id,
            _ag_param({"tenant_id": tenant_id}),
        )
    return 0


def _ag_param(payload: dict) -> str:
    import json as _json

    return _json.dumps(payload)
