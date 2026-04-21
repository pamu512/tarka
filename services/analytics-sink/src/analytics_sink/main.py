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
import re
import sys
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any

import clickhouse_connect
import nats
from fastapi import Depends, FastAPI, HTTPException, Query, Request

from analytics_sink.config import settings

_shared_dir = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", "shared"))
if _shared_dir not in sys.path:
    sys.path.insert(0, _shared_dir)
from observability import get_metrics, setup_observability  # noqa: E402
from tenant_binding import enforce_tenant_access, parse_api_key_tenant_map  # noqa: E402

log = logging.getLogger("analytics-sink")

_ch_client = None
_SAFE_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,127}$")

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
TTL toDateTime(created_at) + toIntervalDay(365)
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
def _get_api_keys() -> frozenset[str]:
    raw = settings.api_keys.strip()
    return frozenset(k.strip() for k in raw.split(",") if k.strip()) if raw else frozenset()


async def require_api_key(request: Request) -> None:
    if request.url.path in {"/v1/health", "/metrics"}:
        return
    keys = _get_api_keys()
    if not keys:
        allow = os.environ.get("ALLOW_INSECURE_NO_AUTH", "").strip().lower() in {"1", "true", "yes", "on"}
        if allow:
            return
        raise HTTPException(
            status_code=503,
            detail="service auth misconfigured: API_KEYS is empty (set API_KEYS or ALLOW_INSECURE_NO_AUTH=true for local development)",
        )
    header = request.headers.get("x-api-key", "")
    if header not in keys:
        raise HTTPException(status_code=401, detail="invalid or missing API key")
    tenant_map = parse_api_key_tenant_map()
    await enforce_tenant_access(request, allowed_tenants=tenant_map.get(header, set()) if tenant_map else None)


def _safe_db_name() -> str:
    db = settings.clickhouse_database.strip()
    if not _SAFE_IDENTIFIER_RE.fullmatch(db):
        raise RuntimeError("Invalid clickhouse_database identifier")
    return db


def _init_clickhouse():
    global _ch_client
    _ch_client = clickhouse_connect.get_client(
        host=settings.clickhouse_host,
        port=settings.clickhouse_port,
        username=settings.clickhouse_user,
        password=settings.clickhouse_password,
    )
    db = _safe_db_name()
    _ch_client.command(f"CREATE DATABASE IF NOT EXISTS {db}")
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
        rows.append(
            [
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
            ]
        )
    try:
        _ch_client.insert(
            f"{db}.decision_events",
            rows,
            column_names=[
                "trace_id",
                "tenant_id",
                "entity_id",
                "event_type",
                "decision",
                "score",
                "tags",
                "rule_hits",
                "signal_tags",
                "ml_score",
                "payload",
                "created_at",
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
    db = _safe_db_name()
    where = ["tenant_id = %(tenant_id)s", "created_at >= now() - INTERVAL %(days)s DAY"]
    params: dict[str, Any] = {
        "tenant_id": tenant_id,
        "days": days,
        "limit": limit,
    }
    if decision:
        where.append("decision = %(decision)s")
        params["decision"] = decision
    if entity_id:
        where.append("entity_id = %(entity_id)s")
        params["entity_id"] = entity_id
    q = f"SELECT * FROM {db}.decision_events WHERE {' AND '.join(where)} ORDER BY created_at DESC LIMIT %(limit)s"
    result = _ch_client.query(q, parameters=params)
    return {"rows": [dict(zip(result.column_names, row)) for row in result.result_rows], "total": len(result.result_rows)}


@app.get("/v1/analytics/hourly")
async def hourly_stats(
    tenant_id: str,
    days: int = Query(default=7, ge=1, le=90),
):
    """Hourly aggregated stats from materialized view."""
    if not _ch_client:
        raise HTTPException(503, "ClickHouse not available")
    db = _safe_db_name()
    q = f"""
    SELECT hour, decision, event_count, avg_score, deny_count, review_count, allow_count
    FROM {db}.hourly_stats
    WHERE tenant_id = %(tenant_id)s AND hour >= now() - INTERVAL %(days)s DAY
    ORDER BY hour DESC
    """
    result = _ch_client.query(q, parameters={"tenant_id": tenant_id, "days": days})
    return {"rows": [dict(zip(result.column_names, row)) for row in result.result_rows]}


@app.get("/v1/analytics/entity/{entity_id}")
async def entity_history(entity_id: str, tenant_id: str, limit: int = 50):
    """Full decision history for a specific entity."""
    if not _ch_client:
        raise HTTPException(503, "ClickHouse not available")
    db = _safe_db_name()
    q = f"""
    SELECT trace_id, event_type, decision, score, tags, rule_hits, ml_score, created_at
    FROM {db}.decision_events
    WHERE tenant_id = %(tenant_id)s AND entity_id = %(entity_id)s
    ORDER BY created_at DESC LIMIT %(limit)s
    """
    result = _ch_client.query(q, parameters={"tenant_id": tenant_id, "entity_id": entity_id, "limit": limit})
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
    db = _safe_db_name()
    q = f"""
    SELECT entity_id, count() AS cnt, avg(score) AS avg_score, groupArray(10)(trace_id) AS sample_traces
    FROM {db}.decision_events
    WHERE tenant_id = %(tenant_id)s AND decision = %(decision)s AND created_at >= now() - INTERVAL %(days)s DAY
    GROUP BY entity_id ORDER BY cnt DESC LIMIT %(limit)s
    """
    result = _ch_client.query(
        q,
        parameters={
            "tenant_id": tenant_id,
            "decision": decision,
            "days": days,
            "limit": limit,
        },
    )
    return {"decision": decision, "entities": [dict(zip(result.column_names, row)) for row in result.result_rows]}


@app.get("/v1/analytics/scorecard")
async def decision_scorecard(
    tenant_id: str,
    days: int = Query(default=7, ge=1, le=90),
):
    """
    OSS #41 / #53 — JSON scorecard over recent decision events.

    Returns a compact, machine-readable summary suitable for publishing to Discussions
    or Trust Center views (not a full report generator).
    """
    if not _ch_client:
        raise HTTPException(503, "ClickHouse not available")
    db = _safe_db_name()
    window_clause = "created_at >= now() - INTERVAL %(days)s DAY"

    # Per-decision aggregates
    q_decisions = f"""
    SELECT
        decision,
        count() AS event_count,
        avg(score) AS avg_score,
        min(score) AS min_score,
        max(score) AS max_score
    FROM {db}.decision_events
    WHERE tenant_id = %(tenant_id)s AND {window_clause}
    GROUP BY decision
    """
    base_params = {"tenant_id": tenant_id, "days": days}
    r_dec = _ch_client.query(q_decisions, parameters=base_params)
    decision_rows = [dict(zip(r_dec.column_names, row)) for row in r_dec.result_rows]
    total_events = sum(int(row.get("event_count", 0)) for row in decision_rows) or 1

    decisions_summary = []
    deny_count = 0
    for row in decision_rows:
        d = str(row.get("decision") or "")
        cnt = int(row.get("event_count", 0))
        if d == "deny":
            deny_count += cnt
        decisions_summary.append(
            {
                "decision": d,
                "event_count": cnt,
                "event_pct": round((cnt / total_events) * 100.0, 2),
                "avg_score": float(row.get("avg_score") or 0.0),
                "min_score": float(row.get("min_score") or 0.0),
                "max_score": float(row.get("max_score") or 0.0),
            }
        )

    # Simple rule-hit frequency slice (top 10).
    q_rules = f"""
    SELECT
        arrayJoin(rule_hits) AS rule_id,
        count() AS hit_count
    FROM {db}.decision_events
    WHERE tenant_id = %(tenant_id)s AND {window_clause}
    GROUP BY rule_id
    ORDER BY hit_count DESC
    LIMIT 10
    """
    r_rules = _ch_client.query(q_rules, parameters=base_params)
    rules_summary = [dict(zip(r_rules.column_names, row)) for row in r_rules.result_rows]

    # Headline metrics.
    deny_rate = round((deny_count / total_events) * 100.0, 2) if total_events else 0.0
    return {
        "tenant_id": tenant_id,
        "window_days": days,
        "total_events": total_events,
        "deny_rate_pct": deny_rate,
        "per_decision": decisions_summary,
        "top_rule_hits": rules_summary,
    }
