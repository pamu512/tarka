"""ClickHouse analytics sink — consumes decision events and exposes query API.

Creates the following ClickHouse tables on startup:
  - fraud.decision_events (MergeTree, partitioned by month)
  - fraud.decision_events_mv (materialized view for hourly aggregates)
"""
import asyncio
import inspect
import json
import logging
import os
import sys
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any

import clickhouse_connect
import nats
from fastapi import Depends, FastAPI, HTTPException, Query, Request
from pydantic import BaseModel, Field

from analytics_sink.config import settings

_shared_dir = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", "shared"))
if _shared_dir not in sys.path:
    sys.path.insert(0, _shared_dir)
from observability import setup_observability, get_metrics  # noqa: E402

log = logging.getLogger("analytics-sink")

_ch_client = None

DDL_EVENTS = """
CREATE TABLE IF NOT EXISTS {db}.decision_events (
    trace_id        String,
    tenant_id       String,
    entity_id       String,
    event_type      String,
    decision        String,
    score           Float64,
    tags            Array(String),
    rule_hits       Array(String),
    signal_tags     Array(String),
    ml_score        Nullable(Float64),
    payload         String,
    created_at      DateTime64(3, 'UTC')
) ENGINE = MergeTree()
PARTITION BY toYYYYMM(created_at)
ORDER BY (tenant_id, entity_id, created_at)
TTL created_at + INTERVAL 365 DAY
"""

DDL_HOURLY_MV = """
CREATE MATERIALIZED VIEW IF NOT EXISTS {db}.hourly_stats
ENGINE = SummingMergeTree()
PARTITION BY toYYYYMM(hour)
ORDER BY (tenant_id, decision, hour)
AS SELECT
    tenant_id,
    decision,
    toStartOfHour(created_at) AS hour,
    count() AS event_count,
    avg(score) AS avg_score,
    countIf(decision = 'deny') AS deny_count,
    countIf(decision = 'review') AS review_count,
    countIf(decision = 'allow') AS allow_count
FROM {db}.decision_events
GROUP BY tenant_id, decision, hour
"""

# ---------- auth ----------
_valid_api_keys: frozenset[str] | None = None

def _get_api_keys() -> frozenset[str]:
    global _valid_api_keys
    if _valid_api_keys is None:
        raw = settings.api_keys.strip()
        _valid_api_keys = frozenset(k.strip() for k in raw.split(",") if k.strip()) if raw else frozenset()
    return _valid_api_keys

async def require_api_key(request: Request) -> None:
    keys = _get_api_keys()
    if not keys:
        return
    if request.headers.get("x-api-key", "") not in keys:
        raise HTTPException(status_code=401, detail="invalid or missing API key")


def _init_clickhouse():
    global _ch_client
    _ch_client = clickhouse_connect.get_client(
        host=settings.clickhouse_host,
        port=settings.clickhouse_port,
        username=settings.clickhouse_user,
        password=settings.clickhouse_password,
    )
    _ch_client.command(f"CREATE DATABASE IF NOT EXISTS {settings.clickhouse_database}")
    db = settings.clickhouse_database
    _ch_client.command(DDL_EVENTS.format(db=db))
    _ch_client.command(DDL_HOURLY_MV.format(db=db))
    log.info("ClickHouse tables initialized in database '%s'", db)


async def _nats_consumer():
    """Subscribe to NATS and write decision results to ClickHouse."""
    try:
        nc = await nats.connect(settings.nats_url)
        js = nc.jetstream()
        subject_pattern = f"{settings.subject_prefix}.>"
        try:
            await js.find_stream_name_by_subject(subject_pattern)
        except Exception:
            await js.add_stream(
                name=settings.stream_name,
                subjects=[subject_pattern],
                retention="limits",
                max_msgs=10_000_000,
                max_bytes=1024 * 1024 * 1024,
                max_age=86400 * 7 * 1_000_000_000,
            )
        sub = await js.pull_subscribe(
            subject_pattern,
            durable="analytics-sink",
            stream=settings.stream_name,
        )
    except Exception as e:
        log.warning("NATS connection failed (analytics sink will only serve queries): %s", e)
        return

    db = settings.clickhouse_database
    batch: list[dict[str, Any]] = []
    FLUSH_SIZE = 100
    FLUSH_INTERVAL = 2.0

    while True:
        try:
            msgs = await sub.fetch(batch=FLUSH_SIZE, timeout=FLUSH_INTERVAL)
            for msg in msgs:
                try:
                    data = json.loads(msg.data.decode())
                    batch.append(data)
                    await msg.ack()
                except Exception as e:
                    log.warning("parse error: %s", e)
                    await msg.ack()

            if batch:
                _flush_batch(db, batch)
                batch = []
        except nats.errors.TimeoutError:
            if batch:
                _flush_batch(db, batch)
                batch = []
            await asyncio.sleep(0.1)
        except Exception as e:
            log.error("NATS consumer error: %s", e)
            await asyncio.sleep(2)


def _flush_batch(db: str, batch: list[dict[str, Any]]) -> None:
    if not _ch_client or not batch:
        return
    rows = []
    for d in batch:
        rows.append([
            d.get("trace_id", ""),
            d.get("tenant_id", ""),
            d.get("entity_id", ""),
            d.get("event_type", ""),
            d.get("decision", "pending"),
            float(d.get("score", 0)),
            d.get("tags", []),
            d.get("rule_hits", []),
            d.get("signal_tags", []),
            d.get("ml_score"),
            json.dumps(d.get("payload", {})),
            datetime.fromisoformat(d["created_at"]) if d.get("created_at") else datetime.now(timezone.utc),
        ])
    try:
        _ch_client.insert(
            f"{db}.decision_events",
            rows,
            column_names=[
                "trace_id", "tenant_id", "entity_id", "event_type",
                "decision", "score", "tags", "rule_hits", "signal_tags",
                "ml_score", "payload", "created_at",
            ],
        )
        try:
            get_metrics().inc("ch_rows_written", len(rows))
        except Exception:
            pass
    except Exception as e:
        log.error("ClickHouse insert failed: %s", e)


@asynccontextmanager
async def lifespan(_: FastAPI):
    _init_clickhouse()
    consumer_coro = _nats_consumer()
    consumer_task = asyncio.create_task(consumer_coro)
    if not isinstance(consumer_task, asyncio.Task) and inspect.iscoroutine(consumer_coro):
        # Test suites may mock create_task; close unscheduled coroutine to avoid leaks.
        consumer_coro.close()
    yield
    consumer_task.cancel()
    try:
        if inspect.isawaitable(consumer_task):
            await consumer_task
    except asyncio.CancelledError:
        pass


app = FastAPI(
    title="Tarka Analytics Sink",
    version="1.0.0",
    lifespan=lifespan,
    dependencies=[Depends(require_api_key)],
)
setup_observability(app, "analytics-sink")


@app.get("/v1/health")
async def health():
    return {"status": "ok", "clickhouse": _ch_client is not None}


@app.get("/v1/analytics/decisions")
async def query_decisions(
    tenant_id: str,
    days: int = Query(default=7, ge=1, le=365),
    decision: str | None = None,
    entity_id: str | None = None,
    limit: int = Query(default=100, ge=1, le=10000),
):
    """Query recent decision events from ClickHouse."""
    if not _ch_client:
        raise HTTPException(503, "ClickHouse not available")
    db = settings.clickhouse_database
    where = [f"tenant_id = '{tenant_id}'", f"created_at >= now() - INTERVAL {days} DAY"]
    if decision:
        where.append(f"decision = '{decision}'")
    if entity_id:
        where.append(f"entity_id = '{entity_id}'")
    q = f"SELECT * FROM {db}.decision_events WHERE {' AND '.join(where)} ORDER BY created_at DESC LIMIT {limit}"
    result = _ch_client.query(q)
    return {"rows": [dict(zip(result.column_names, row)) for row in result.result_rows], "total": len(result.result_rows)}


@app.get("/v1/analytics/hourly")
async def hourly_stats(
    tenant_id: str,
    days: int = Query(default=7, ge=1, le=90),
):
    """Hourly aggregated stats from materialized view."""
    if not _ch_client:
        raise HTTPException(503, "ClickHouse not available")
    db = settings.clickhouse_database
    q = f"""
    SELECT hour, decision, event_count, avg_score, deny_count, review_count, allow_count
    FROM {db}.hourly_stats
    WHERE tenant_id = '{tenant_id}' AND hour >= now() - INTERVAL {days} DAY
    ORDER BY hour DESC
    """
    result = _ch_client.query(q)
    return {"rows": [dict(zip(result.column_names, row)) for row in result.result_rows]}


@app.get("/v1/analytics/entity/{entity_id}")
async def entity_history(entity_id: str, tenant_id: str, limit: int = 50):
    """Full decision history for a specific entity."""
    if not _ch_client:
        raise HTTPException(503, "ClickHouse not available")
    db = settings.clickhouse_database
    q = f"""
    SELECT trace_id, event_type, decision, score, tags, rule_hits, ml_score, created_at
    FROM {db}.decision_events
    WHERE tenant_id = '{tenant_id}' AND entity_id = '{entity_id}'
    ORDER BY created_at DESC LIMIT {limit}
    """
    result = _ch_client.query(q)
    return {"entity_id": entity_id, "events": [dict(zip(result.column_names, row)) for row in result.result_rows]}


@app.get("/v1/analytics/top-entities")
async def top_entities(
    tenant_id: str,
    days: int = Query(default=7, ge=1, le=90),
    decision: str = "deny",
    limit: int = 20,
):
    """Top entities by decision count."""
    if not _ch_client:
        raise HTTPException(503, "ClickHouse not available")
    db = settings.clickhouse_database
    q = f"""
    SELECT entity_id, count() AS cnt, avg(score) AS avg_score, groupArray(10)(trace_id) AS sample_traces
    FROM {db}.decision_events
    WHERE tenant_id = '{tenant_id}' AND decision = '{decision}' AND created_at >= now() - INTERVAL {days} DAY
    GROUP BY entity_id ORDER BY cnt DESC LIMIT {limit}
    """
    result = _ch_client.query(q)
    return {"decision": decision, "entities": [dict(zip(result.column_names, row)) for row in result.result_rows]}
