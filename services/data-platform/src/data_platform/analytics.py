"""Postgres analytics helpers for data-platform."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

import asyncpg


CREATE_SCHEMA_SQL = "CREATE SCHEMA IF NOT EXISTS analytics;"

CREATE_PARTITIONED_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS analytics.decision_events (
  id BIGSERIAL NOT NULL,
  stream_id TEXT NOT NULL,
  tenant_id TEXT NOT NULL,
  entity_id TEXT NOT NULL,
  event_type TEXT NOT NULL,
  decision TEXT NOT NULL,
  score DOUBLE PRECISION NOT NULL DEFAULT 0,
  payload JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  PRIMARY KEY (id, created_at)
) PARTITION BY RANGE (created_at);
"""

CREATE_LEGACY_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS analytics.decision_events (
  id BIGSERIAL PRIMARY KEY,
  stream_id TEXT NOT NULL,
  tenant_id TEXT NOT NULL,
  entity_id TEXT NOT NULL,
  event_type TEXT NOT NULL,
  decision TEXT NOT NULL,
  score DOUBLE PRECISION NOT NULL DEFAULT 0,
  payload JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
"""

CREATE_INDEX_SQL = "CREATE INDEX IF NOT EXISTS idx_decision_events_tenant_created ON analytics.decision_events (tenant_id, created_at DESC);"


def _month_start(dt: datetime) -> datetime:
    return datetime(dt.year, dt.month, 1, tzinfo=UTC)


def _next_month_start(dt: datetime) -> datetime:
    if dt.month == 12:
        return datetime(dt.year + 1, 1, 1, tzinfo=UTC)
    return datetime(dt.year, dt.month + 1, 1, tzinfo=UTC)


async def _is_partitioned(conn: asyncpg.Connection) -> bool:
    row = await conn.fetchrow(
        """
        SELECT EXISTS (
          SELECT 1
          FROM pg_partitioned_table p
          JOIN pg_class c ON c.oid = p.partrelid
          JOIN pg_namespace n ON n.oid = c.relnamespace
          WHERE n.nspname = 'analytics' AND c.relname = 'decision_events'
        ) AS is_partitioned
        """
    )
    return bool(row and row["is_partitioned"])


async def _table_exists(conn: asyncpg.Connection) -> bool:
    row = await conn.fetchrow(
        """
        SELECT to_regclass('analytics.decision_events') IS NOT NULL AS exists
        """
    )
    return bool(row and row["exists"])


async def _ensure_month_partition(conn: asyncpg.Connection, start: datetime, end: datetime) -> None:
    pname = f"decision_events_{start.year}{start.month:02d}"
    start_s = start.isoformat()
    end_s = end.isoformat()
    await conn.execute(
        f"""
        CREATE TABLE IF NOT EXISTS analytics.{pname}
        PARTITION OF analytics.decision_events
        FOR VALUES FROM ('{start_s}') TO ('{end_s}')
        """
    )


async def _ensure_partitions(conn: asyncpg.Connection) -> None:
    await conn.execute(
        """
        CREATE TABLE IF NOT EXISTS analytics.decision_events_default
        PARTITION OF analytics.decision_events DEFAULT
        """
    )
    now = datetime.now(UTC)
    current_start = _month_start(now)
    next_start = _next_month_start(current_start)
    after_next = _next_month_start(next_start)
    await _ensure_month_partition(conn, current_start, next_start)
    await _ensure_month_partition(conn, next_start, after_next)


async def ensure_schema(pool: asyncpg.Pool) -> None:
    async with pool.acquire() as conn:
        await conn.execute(CREATE_SCHEMA_SQL)
        exists = await _table_exists(conn)
        if not exists:
            await conn.execute(CREATE_PARTITIONED_TABLE_SQL)
            await conn.execute(CREATE_INDEX_SQL)
            await _ensure_partitions(conn)
            return

        if await _is_partitioned(conn):
            await conn.execute(CREATE_INDEX_SQL)
            await _ensure_partitions(conn)
            return

        # Legacy non-partitioned table compatibility path.
        await conn.execute(CREATE_LEGACY_TABLE_SQL)
        await conn.execute(CREATE_INDEX_SQL)


def _to_json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, default=str, separators=(",", ":"))


async def write_event(pool: asyncpg.Pool, stream_id: str, event: dict[str, Any]) -> None:
    tenant_id = str(event.get("tenant_id") or "")
    entity_id = str(event.get("entity_id") or "")
    event_type = str(event.get("event_type") or "")
    decision = str(event.get("decision") or "pending")
    score_raw = event.get("score")
    score = float(score_raw) if isinstance(score_raw, (int, float, str)) and str(score_raw) else 0.0
    created_at = event.get("created_at")
    ts: datetime
    if isinstance(created_at, str) and created_at:
        try:
            ts = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
        except ValueError:
            ts = datetime.now(UTC)
    else:
        ts = datetime.now(UTC)
    payload = dict(event.get("payload") or {})
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO analytics.decision_events
              (stream_id, tenant_id, entity_id, event_type, decision, score, payload, created_at)
            VALUES ($1,$2,$3,$4,$5,$6,$7::jsonb,$8)
            """,
            stream_id,
            tenant_id,
            entity_id,
            event_type,
            decision,
            score,
            _to_json(payload),
            ts,
        )


async def query_decisions(
    pool: asyncpg.Pool,
    tenant_id: str,
    days: int,
    limit: int,
    decision: str | None = None,
    entity_id: str | None = None,
) -> list[dict[str, Any]]:
    where = ["tenant_id = $1", "created_at >= NOW() - ($2::text || ' days')::interval"]
    args: list[Any] = [tenant_id, max(1, min(days, 365))]
    idx = 3
    if decision:
        where.append(f"decision = ${idx}")
        args.append(decision)
        idx += 1
    if entity_id:
        where.append(f"entity_id = ${idx}")
        args.append(entity_id)
        idx += 1
    args.append(max(1, min(limit, 10_000)))
    q = f"""
      SELECT stream_id, tenant_id, entity_id, event_type, decision, score, payload, created_at
      FROM analytics.decision_events
      WHERE {' AND '.join(where)}
      ORDER BY created_at DESC
      LIMIT ${idx}
    """
    async with pool.acquire() as conn:
        rows = await conn.fetch(q, *args)
    return [dict(r) for r in rows]

