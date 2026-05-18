"""Data platform service (Lite path): Redis Streams + Postgres analytics."""

from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from typing import Any

import asyncpg
import redis.asyncio as aioredis
from fastapi import Depends, FastAPI, HTTPException, Query, Request
from pydantic import BaseModel, Field

from data_platform.analytics import ensure_schema, query_decisions, write_event
from data_platform.config import settings
from data_platform.streaming import ensure_group, parse_stream_event, publish_event
from tarka_shared.config_validation import log_runtime_warnings
from tarka_shared.observability import get_metrics, setup_observability
from tarka_shared.tracing import setup_tracing

log = logging.getLogger("data-platform")


class EventPayload(BaseModel):
    tenant_id: str
    event_type: str
    entity_id: str
    decision: str = "pending"
    score: float = 0.0
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: str | None = None


def _get_api_keys() -> frozenset[str]:
    raw = settings.api_keys.strip()
    return frozenset(k.strip() for k in raw.split(",") if k.strip()) if raw else frozenset()


async def require_api_key(request: Request) -> None:
    if request.url.path in {"/v1/health", "/metrics"}:
        return
    keys = _get_api_keys()
    if not keys:
        allow = settings.allow_insecure_no_auth or os.environ.get(
            "ALLOW_INSECURE_NO_AUTH", ""
        ).lower() in {"1", "true", "yes", "on"}
        if allow:
            return
        raise HTTPException(status_code=503, detail="service auth misconfigured: API_KEYS is empty")
    if request.headers.get("x-api-key", "") not in keys:
        raise HTTPException(status_code=401, detail="invalid or missing API key")


async def _consumer_loop(app: FastAPI) -> None:
    redis: aioredis.Redis = app.state.redis
    pool: asyncpg.Pool = app.state.pg_pool
    await ensure_group(redis, settings.redis_stream, settings.redis_consumer_group)
    while True:
        try:
            rows = await redis.xreadgroup(
                groupname=settings.redis_consumer_group,
                consumername=settings.redis_consumer_name,
                streams={settings.redis_stream: ">"},
                count=max(1, settings.redis_batch_size),
                block=max(0, settings.redis_block_ms),
            )
            if not rows:
                continue
            for _, events in rows:
                for stream_id, fields in events:
                    parsed = parse_stream_event(fields)
                    if not parsed:
                        await redis.xack(
                            settings.redis_stream, settings.redis_consumer_group, stream_id
                        )
                        continue
                    await write_event(pool, stream_id, parsed)
                    await redis.xack(
                        settings.redis_stream, settings.redis_consumer_group, stream_id
                    )
                    try:
                        get_metrics().inc("data_platform_events_written_total")
                    except Exception:
                        pass
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.warning("consumer loop error: %s", exc)
            await asyncio.sleep(1.0)


@asynccontextmanager
async def lifespan(app: FastAPI):
    log_runtime_warnings("data-platform")
    app.state.redis = aioredis.from_url(settings.redis_url, decode_responses=True)
    await app.state.redis.ping()
    app.state.pg_pool = await asyncpg.create_pool(
        dsn=settings.database_url, min_size=1, max_size=10
    )
    await ensure_schema(app.state.pg_pool)
    app.state.consumer_task = None
    if settings.enable_consumer:
        app.state.consumer_task = asyncio.create_task(_consumer_loop(app))
    yield
    task = app.state.consumer_task
    if task is not None:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
    await app.state.redis.aclose()
    await app.state.pg_pool.close()


app = FastAPI(
    title="Tarka Data Platform",
    version="0.1.0",
    lifespan=lifespan,
    dependencies=[Depends(require_api_key)],
)
setup_observability(app, "data-platform")
setup_tracing(app, "data-platform")


@app.get("/v1/health")
async def health(request: Request) -> dict[str, Any]:
    redis_ok = False
    pg_ok = False
    try:
        await request.app.state.redis.ping()
        redis_ok = True
    except Exception:
        redis_ok = False
    try:
        async with request.app.state.pg_pool.acquire() as conn:
            await conn.fetchval("SELECT 1")
        pg_ok = True
    except Exception:
        pg_ok = False
    return {"status": "ok", "redis_ok": redis_ok, "postgres_ok": pg_ok}


@app.post("/v1/events", dependencies=[Depends(require_api_key)])
async def ingest_event(body: EventPayload, request: Request) -> dict[str, Any]:
    stream_id = await publish_event(
        request.app.state.redis, settings.redis_stream, body.model_dump(mode="json")
    )
    try:
        get_metrics().inc("data_platform_events_ingested_total")
    except Exception:
        pass
    return {"accepted": True, "stream_id": stream_id}


@app.post("/v1/events/batch", dependencies=[Depends(require_api_key)])
async def ingest_batch(body: dict[str, Any], request: Request) -> dict[str, Any]:
    events = body.get("events")
    if not isinstance(events, list):
        raise HTTPException(status_code=422, detail="events must be an array")
    results: list[str] = []
    for item in events:
        evt = EventPayload.model_validate(item)
        sid = await publish_event(
            request.app.state.redis, settings.redis_stream, evt.model_dump(mode="json")
        )
        results.append(sid)
    try:
        get_metrics().inc("data_platform_events_ingested_total", len(results))
    except Exception:
        pass
    return {"accepted": len(results), "results": results}


@app.get("/v1/stream/info", dependencies=[Depends(require_api_key)])
async def stream_info(request: Request) -> dict[str, Any]:
    size = await request.app.state.redis.xlen(settings.redis_stream)
    return {
        "backend": "redis_streams",
        "stream": settings.redis_stream,
        "consumer_group": settings.redis_consumer_group,
        "length": int(size),
    }


@app.get("/v1/analytics/decisions", dependencies=[Depends(require_api_key)])
async def analytics_decisions(
    request: Request,
    tenant_id: str,
    days: int = Query(default=7, ge=1, le=365),
    limit: int = Query(default=100, ge=1, le=10_000),
    decision: str | None = None,
    entity_id: str | None = None,
) -> dict[str, Any]:
    rows = await query_decisions(
        request.app.state.pg_pool,
        tenant_id=tenant_id,
        days=days,
        limit=limit,
        decision=decision,
        entity_id=entity_id,
    )
    return {"rows": rows, "total": len(rows), "backend": settings.analytics_backend}
