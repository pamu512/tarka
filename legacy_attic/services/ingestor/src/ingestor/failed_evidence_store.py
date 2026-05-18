"""Postgres dead-letter queue for failed EvidenceManifest ClickHouse writes."""

from __future__ import annotations

import logging
from typing import Any

import asyncpg

from ingestor.settings import IngestorSettings

logger = logging.getLogger(__name__)


async def create_pool(settings: IngestorSettings) -> asyncpg.Pool:
    if not settings.postgres_dsn.strip():
        raise ValueError("postgres_dsn is empty")
    return await asyncpg.create_pool(
        settings.postgres_dsn,
        min_size=1,
        max_size=settings.postgres_pool_max_size,
        command_timeout=settings.postgres_command_timeout_s,
    )


async def insert_failed_manifest(
    pool: asyncpg.Pool,
    *,
    raw_manifest: bytes,
    manifest_b64: str,
    last_error: str,
    failure_phase: str = "clickhouse_insert",
) -> int:
    """Persist a failed manifest for later replay. Returns row id."""
    err = last_error[:16000] if last_error else "unknown"
    async with pool.acquire() as conn:
        row_id = await conn.fetchval(
            """
            INSERT INTO failed_evidence (
                raw_manifest, manifest_b64, last_error, failure_phase
            )
            VALUES ($1, $2, $3, $4)
            RETURNING id
            """,
            raw_manifest,
            manifest_b64,
            err,
            failure_phase[:128],
        )
    assert row_id is not None
    logger.warning(
        "recorded failed_evidence row",
        extra={"failed_evidence_id": int(row_id), "phase": failure_phase},
    )
    return int(row_id)


async def fetch_pending_batch(pool: asyncpg.Pool, *, limit: int) -> list[asyncpg.Record]:
    """Oldest pending rows. Intended for a single replay worker (no row-level lock)."""
    async with pool.acquire() as conn:
        return await conn.fetch(
            """
            SELECT id, raw_manifest, manifest_b64, replay_attempts
            FROM failed_evidence
            WHERE status = 'pending'
            ORDER BY id
            LIMIT $1
            """,
            limit,
        )


async def mark_replayed(pool: asyncpg.Pool, row_id: int) -> None:
    async with pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE failed_evidence
            SET status = 'replayed',
                replayed_at = now(),
                updated_at = now(),
                last_replay_error = NULL
            WHERE id = $1
            """,
            row_id,
        )


async def mark_replay_failure(
    pool: asyncpg.Pool,
    row_id: int,
    *,
    error: str,
    max_attempts: int,
) -> None:
    err = error[:16000] if error else "unknown"
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            UPDATE failed_evidence
            SET replay_attempts = replay_attempts + 1,
                last_replay_error = $2,
                updated_at = now(),
                status = CASE
                    WHEN replay_attempts + 1 >= $3 THEN 'abandoned'
                    ELSE status
                END
            WHERE id = $1
            RETURNING replay_attempts, status
            """,
            row_id,
            err,
            max_attempts,
        )
    if row and row["status"] == "abandoned":
        logger.error(
            "failed_evidence abandoned after max replay attempts",
            extra={"failed_evidence_id": row_id, "attempts": row["replay_attempts"]},
        )


async def row_snapshot(pool: asyncpg.Pool, row_id: int) -> dict[str, Any] | None:
    async with pool.acquire() as conn:
        r = await conn.fetchrow(
            "SELECT id, status, replay_attempts FROM failed_evidence WHERE id = $1",
            row_id,
        )
    return dict(r) if r else None
