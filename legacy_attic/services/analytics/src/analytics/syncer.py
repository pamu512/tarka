"""Postgres ``inference_logs`` → ClickHouse mirror with idempotent upserts and bounded concurrency.

ClickHouse has no MySQL-style ``ON DUPLICATE KEY UPDATE``; we use ``ReplacingMergeTree(_version)``
so repeated inserts for the same ``id`` coalesce to the latest row. After each insert we verify
``uniqExact(id)`` for the batch keys matches the Postgres batch size before marking ``SYNCED``.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, TypeVar
from uuid import UUID

import anyio
import asyncpg
from clickhouse_connect.driver.client import Client

from analytics.queries import validate_sql_identifier

log = logging.getLogger("analytics.syncer")

T = TypeVar("T")

_CH_ROW_COLUMNS = (
    "id",
    "trace_id",
    "tenant_id",
    "entity_id",
    "event_type",
    "decision",
    "score",
    "tags",
    "rule_hits",
    "payload_snapshot",
    "created_at",
    "_version",
)


def _json_text(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, (dict, list)):
        return json.dumps(v, default=str, separators=(",", ":"))
    return json.dumps(v, default=str, separators=(",", ":"))


def _fq_table(database: str, table: str) -> str:
    d = validate_sql_identifier(database.strip())
    t = validate_sql_identifier(table.strip())
    return f"`{d}`.`{t}`"


def _next_retry_delay_seconds(
    *,
    failure_count_before_increment: int,
    backoff_base_sec: float,
    backoff_max_sec: float,
) -> float:
    exp = min(20, max(0, failure_count_before_increment))
    return float(min(backoff_max_sec, backoff_base_sec * (2.0**exp)))


def _ensure_clickhouse_table(client: Client, fq_table: str) -> None:
    """Create ReplacingMergeTree table if missing (idempotent DDL)."""
    ddl = f"""
CREATE TABLE IF NOT EXISTS {fq_table} (
  id UUID,
  trace_id UUID,
  tenant_id String,
  entity_id String,
  event_type LowCardinality(String),
  decision LowCardinality(String),
  score Float64,
  tags String,
  rule_hits String,
  payload_snapshot Nullable(String),
  created_at DateTime64(3, 'UTC'),
  _version DateTime64(3, 'UTC')
) ENGINE = ReplacingMergeTree(_version)
ORDER BY (id)
"""
    client.command(ddl)


def _records_to_ch_rows(records: Sequence[asyncpg.Record], version: datetime) -> list[list[Any]]:
    rows: list[list[Any]] = []
    v = version.astimezone(UTC).replace(tzinfo=None)
    for r in records:
        created = r["created_at"]
        if created.tzinfo is None:
            created = created.replace(tzinfo=UTC)
        created_naive = created.astimezone(UTC).replace(tzinfo=None)
        ps = r["payload_snapshot"]
        rows.append(
            [
                r["id"],
                r["trace_id"],
                r["tenant_id"],
                r["entity_id"],
                r["event_type"],
                r["decision"],
                float(r["score"]),
                _json_text(r["tags"]),
                _json_text(r["rule_hits"]),
                None if ps is None else _json_text(ps),
                created_naive,
                v,
            ]
        )
    return rows


@dataclass
class SyncWorkerConfig:
    batch_size: int = 1000
    max_concurrent_batches: int = 4
    clickhouse_table: str = "inference_logs_ch"
    backoff_base_sec: float = 2.0
    backoff_max_sec: float = 3600.0


@dataclass
class SyncWorkerStats:
    rows_fetched: int = 0
    rows_marked_synced: int = 0
    rows_marked_failed: int = 0
    chunks_ok: int = 0
    chunks_failed: int = 0


class SyncWorker:
    """Background-style worker: pull PENDING (and due FAILED) rows, upsert to ClickHouse, verify counts."""

    _FETCH_SQL = """
SELECT
  id, trace_id, tenant_id, entity_id, event_type, decision, score,
  tags, rule_hits, payload_snapshot, created_at,
  sync_status, sync_failure_count
FROM inference_logs
WHERE (
  sync_status = 'PENDING'
  OR (
    sync_status = 'FAILED'
    AND sync_next_retry_at IS NOT NULL
    AND sync_next_retry_at <= now()
  )
)
ORDER BY created_at ASC
LIMIT $1
"""

    def __init__(
        self,
        pg_pool: asyncpg.Pool,
        clickhouse_client: Client,
        *,
        clickhouse_database: str,
        config: SyncWorkerConfig | None = None,
        run_clickhouse_sync: Callable[[Callable[[], Any]], Any] | None = None,
    ) -> None:
        self._pool = pg_pool
        self._ch = clickhouse_client
        self._ch_db = clickhouse_database.strip() or "default"
        self.config = config or SyncWorkerConfig()
        self._run_ch: Callable[[Callable[[], Any]], Any] = run_clickhouse_sync or (
            lambda fn: anyio.to_thread.run_sync(fn)
        )

    @property
    def _fq(self) -> str:
        return _fq_table(self._ch_db, self.config.clickhouse_table)

    async def ensure_clickhouse_destination(self) -> None:
        """Idempotent DDL for the ReplacingMergeTree destination table."""

        def _go() -> None:
            _ensure_clickhouse_table(self._ch, self._fq)

        await self._run_ch(_go)

    async def _ch_insert_versioned(self, ch_rows: list[list[Any]]) -> None:
        def _go() -> None:
            self._ch.insert(
                self.config.clickhouse_table,
                ch_rows,
                column_names=list(_CH_ROW_COLUMNS),
                database=self._ch_db,
            )

        await self._run_ch(_go)

    async def _ch_uniq_count_for_ids(self, ids: list[UUID]) -> int:
        if not ids:
            return 0
        id_literals = ",".join(str(u) for u in ids)
        sql = f"SELECT uniqExact(id) AS c FROM {self._fq} WHERE id IN ({id_literals})"

        def _go() -> int:
            r = self._ch.query(sql)
            if not r.result_rows:
                return 0
            return int(r.result_rows[0][0])

        return int(await self._run_ch(_go))

    async def _mark_synced(self, conn: asyncpg.Connection, ids: list[UUID]) -> int:
        if not ids:
            return 0
        res = await conn.execute(
            """
UPDATE inference_logs
SET
  sync_status = 'SYNCED',
  synced_at = now(),
  sync_error = NULL,
  sync_failure_count = 0,
  sync_next_retry_at = NULL
WHERE id = ANY($1::uuid[])
  AND (
    sync_status = 'PENDING'
    OR (
      sync_status = 'FAILED'
      AND sync_next_retry_at IS NOT NULL
      AND sync_next_retry_at <= now()
    )
  )
""",
            ids,
        )
        # asyncpg returns 'UPDATE N'
        parts = res.split()
        return int(parts[-1]) if parts else 0

    async def _mark_failed(
        self,
        conn: asyncpg.Connection,
        ids: list[UUID],
        error_message: str,
        *,
        max_failure_count_before: int,
    ) -> None:
        if not ids:
            return
        delay = _next_retry_delay_seconds(
            failure_count_before_increment=max_failure_count_before,
            backoff_base_sec=self.config.backoff_base_sec,
            backoff_max_sec=self.config.backoff_max_sec,
        )
        next_at = datetime.now(UTC) + timedelta(seconds=delay)
        await conn.execute(
            """
UPDATE inference_logs
SET
  sync_status = 'FAILED',
  sync_error = $1,
  sync_failure_count = sync_failure_count + 1,
  sync_next_retry_at = $2
WHERE id = ANY($3::uuid[])
""",
            error_message[:8192],
            next_at,
            ids,
        )

    async def _process_chunk(self, chunk: list[asyncpg.Record], stats: SyncWorkerStats) -> None:
        ids = [r["id"] for r in chunk]
        max_fail_before = max(int(r["sync_failure_count"] or 0) for r in chunk)
        version = datetime.now(UTC)
        ch_rows = _records_to_ch_rows(chunk, version)
        try:
            await self._ch_insert_versioned(ch_rows)
            uniq = await self._ch_uniq_count_for_ids(ids)
            if uniq != len(ids):
                msg = (
                    f"clickhouse_row_count_mismatch: expected_uniqExact_id={len(ids)} "
                    f"got={uniq} (batch not marked SYNCED)"
                )
                log.warning("%s", msg)
                async with self._pool.acquire() as conn:
                    await self._mark_failed(
                        conn, ids, msg, max_failure_count_before=max_fail_before
                    )
                stats.rows_marked_failed += len(ids)
                stats.chunks_failed += 1
                return

            async with self._pool.acquire() as conn:
                n = await self._mark_synced(conn, ids)
            stats.rows_marked_synced += n
            stats.chunks_ok += 1
            if n != len(ids):
                log.info(
                    "inference_logs sync: marked %s rows SYNCED (expected %s; concurrent worker likely updated overlap)",
                    n,
                    len(ids),
                )
        except Exception as e:
            msg = f"{type(e).__name__}: {e}"
            log.exception("inference_logs sync chunk failed: %s", msg)
            async with self._pool.acquire() as conn:
                await self._mark_failed(conn, ids, msg, max_failure_count_before=max_fail_before)
            stats.rows_marked_failed += len(ids)
            stats.chunks_failed += 1

    async def run_cycle(self) -> SyncWorkerStats:
        """One drain cycle: up to ``batch_size * max_concurrent_batches`` eligible rows, chunked with bounded gather."""
        stats = SyncWorkerStats()
        limit = self.config.batch_size * max(1, self.config.max_concurrent_batches)
        async with self._pool.acquire() as conn:
            recs = await conn.fetch(self._FETCH_SQL, limit)
        if not recs:
            return stats
        stats.rows_fetched = len(recs)
        chunks: list[list[asyncpg.Record]] = []
        for i in range(0, len(recs), self.config.batch_size):
            chunks.append(list(recs[i : i + self.config.batch_size]))
        await gather_with_concurrency(
            [self._process_chunk(c, stats) for c in chunks],
            self.config.max_concurrent_batches,
        )
        return stats

    async def run_reconcile_cycle(self) -> SyncWorkerStats:
        """Alias for the same eligibility filter (FAILED rows become eligible when ``sync_next_retry_at`` passes)."""
        return await self.run_cycle()


async def gather_with_concurrency(awaitables: Sequence[Awaitable[T]], limit: int) -> list[T]:
    """``asyncio.gather`` with a shared semaphore so callers do not exhaust Postgres/HTTP pools."""
    sem = asyncio.Semaphore(max(1, limit))

    async def _wrap(aw: Awaitable[T]) -> T:
        async with sem:
            return await aw

    return list(await asyncio.gather(*(_wrap(aw) for aw in awaitables)))
