"""Postgres ↔ Redis sync for entity tag signatures (stateful fraud cache).

Redis keys ``fraud:tags:{tenant_id}:{entity_id}`` back the Rust/Python rule engine merge path.
Postgres table ``entity_signature_state`` is the durable source of truth; this module repopulates
Redis when keys are missing or drift from Postgres (self-healing after eviction / failover).
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from typing import Any

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from decision_api.config import settings
from decision_api.db import SessionLocal
from decision_api.models import EntitySignatureState
from decision_api.redis_store import RedisTags, redis_tags
from tarka_core.internal_monitor import InternalMonitor

log = logging.getLogger("decision-api.redis_signature_sync")


def canonical_tags_blob(tags: list[str]) -> str:
    """Deterministic JSON matching :meth:`RedisTags.set_tags` / Lua merge output."""
    normalized = sorted({str(t) for t in tags})
    return json.dumps(normalized, separators=(",", ":"))


def content_sha256_hex(blob: str) -> str:
    return hashlib.sha256(blob.encode()).hexdigest()


def _tags_equivalent(redis_raw: str | None, pg_tags: list[Any]) -> bool:
    if redis_raw is None:
        return False
    try:
        parsed = json.loads(redis_raw)
    except json.JSONDecodeError:
        return False
    if not isinstance(parsed, list):
        return False
    left = sorted(str(x) for x in parsed)
    right = sorted(str(x) for x in pg_tags)
    return left == right


async def upsert_entity_signature_state(
    session: AsyncSession,
    tenant_id: str,
    entity_id: str,
    tags: list[str],
) -> None:
    """Persist canonical merged tags as the Postgres source-of-truth row."""
    normalized = sorted({str(t) for t in tags})
    blob = canonical_tags_blob(tags)
    digest = content_sha256_hex(blob)
    stmt = select(EntitySignatureState).where(
        EntitySignatureState.tenant_id == tenant_id,
        EntitySignatureState.entity_id == entity_id,
    )
    existing = (await session.execute(stmt)).scalar_one_or_none()
    if existing:
        existing.tags_json = normalized
        existing.content_sha256 = digest
    else:
        session.add(
            EntitySignatureState(
                tenant_id=tenant_id,
                entity_id=entity_id,
                tags_json=normalized,
                content_sha256=digest,
            )
        )


async def persist_entity_signature_after_evaluate(
    tenant_id: str,
    entity_id: str,
    tags: list[str],
) -> None:
    """Background task: record merged tags after evaluation (best-effort)."""
    try:
        async with SessionLocal() as session:
            await upsert_entity_signature_state(session, tenant_id, entity_id, tags)
            await session.commit()
    except Exception as exc:
        InternalMonitor.log_suppressed_error(
            exc,
            context="entity_signature_state_upsert_evaluate",
            domain="redis_signature_sync",
            level=logging.WARNING,
            tenant_id=tenant_id,
            entity_id=entity_id,
        )


async def _fetch_redis_raw_batch(
    store: RedisTags, rows: list[EntitySignatureState]
) -> list[str | None]:
    keys = [store._key_tags(r.tenant_id, r.entity_id) for r in rows]
    if store._client is not None:
        raw = await store._client.mget(keys)
        out: list[str | None] = []
        for v in raw:
            if v is None:
                out.append(None)
            elif isinstance(v, bytes):
                out.append(v.decode())
            else:
                out.append(str(v))
        return out
    out = []
    for r in rows:
        tags = await store.get_tags(r.tenant_id, r.entity_id)
        out.append(canonical_tags_blob(tags) if tags else None)
    return out


async def reconcile_batch(
    store: RedisTags,
    rows: list[EntitySignatureState],
) -> tuple[int, int]:
    """Return (missing_repopulated, drift_corrected). Batch Redis reads via ``MGET`` when available."""
    if not rows:
        return 0, 0
    redis_vals = await _fetch_redis_raw_batch(store, rows)
    missing = 0
    drift = 0
    for row, raw in zip(rows, redis_vals, strict=True):
        if _tags_equivalent(raw, list(row.tags_json)):
            continue
        try:
            await store.set_tags(row.tenant_id, row.entity_id, list(row.tags_json))
        except Exception as exc:
            InternalMonitor.log_suppressed_error(
                exc,
                context="redis_signature_sync_set_tags_failed",
                domain="redis_signature_sync",
                level=logging.WARNING,
                tenant_id=row.tenant_id,
                entity_id=row.entity_id,
            )
            continue
        if raw is None:
            missing += 1
        else:
            drift += 1
    return missing, drift


async def run_signature_sync_cycle(
    session: AsyncSession,
    store: RedisTags,
) -> dict[str, int]:
    """Scan Postgres in batches and heal Redis."""
    batch_size = settings.redis_signature_sync_batch_size
    last_t = ""
    last_e = ""
    total_missing = 0
    total_drift = 0
    total_rows = 0

    while True:
        cond = or_(
            EntitySignatureState.tenant_id > last_t,
            and_(
                EntitySignatureState.tenant_id == last_t,
                EntitySignatureState.entity_id > last_e,
            ),
        )
        stmt = (
            select(EntitySignatureState)
            .where(cond)
            .order_by(
                EntitySignatureState.tenant_id.asc(),
                EntitySignatureState.entity_id.asc(),
            )
            .limit(batch_size)
        )
        rows = list((await session.execute(stmt)).scalars().all())
        if not rows:
            break
        total_rows += len(rows)
        try:
            m, d = await reconcile_batch(store, rows)
            total_missing += m
            total_drift += d
        except Exception as exc:
            InternalMonitor.log_suppressed_error(
                exc,
                context="redis_signature_sync_batch_failed",
                domain="redis_signature_sync",
                level=logging.ERROR,
                batch_first_tenant=rows[0].tenant_id,
                batch_first_entity=rows[0].entity_id,
            )
            raise
        last_t = rows[-1].tenant_id
        last_e = rows[-1].entity_id

    return {
        "rows_scanned": total_rows,
        "redis_missing_repopulated": total_missing,
        "redis_drift_corrected": total_drift,
    }


async def redis_signature_sync_loop() -> None:
    """Periodic reconcile loop (bounded batches per cycle)."""
    backoff_s = 5.0
    max_backoff_s = 300.0
    while True:
        await asyncio.sleep(settings.redis_signature_sync_interval_seconds)
        try:
            await redis_tags.connect()
            async with SessionLocal() as session:
                stats = await run_signature_sync_cycle(session, redis_tags)
            if stats["rows_scanned"] > 0 or stats["redis_missing_repopulated"] > 0:
                log.info(
                    "redis_signature_sync cycle rows=%s repopulated=%s drift_fixed=%s",
                    stats["rows_scanned"],
                    stats["redis_missing_repopulated"],
                    stats["redis_drift_corrected"],
                )
            backoff_s = 5.0
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            InternalMonitor.log_suppressed_error(
                exc,
                context="redis_signature_sync_cycle_failed",
                domain="redis_signature_sync",
                level=logging.ERROR,
            )
            log.warning(
                "redis_signature_sync cycle failed: %s (retry in %.1fs)",
                exc,
                backoff_s,
            )
            await asyncio.sleep(backoff_s)
            backoff_s = min(max_backoff_s, backoff_s * 2.0)


async def run_signature_sync_once() -> dict[str, int]:
    """Operator hook / CLI: single reconcile pass."""
    await redis_tags.connect()
    async with SessionLocal() as session:
        return await run_signature_sync_cycle(session, redis_tags)


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    stats = asyncio.run(run_signature_sync_once())
    print(json.dumps(stats, indent=2))


if __name__ == "__main__":
    main()
