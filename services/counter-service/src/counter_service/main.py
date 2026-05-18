import os
import sys
import uuid
from datetime import datetime, timezone
from typing import Any

import redis.asyncio as aioredis
from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel, Field

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", "shared"))
from auth import require_api_key  # noqa: E402
from fraud_aggregates import AggregateStore, normalized_velocity_key_names  # noqa: E402
from observability import get_metrics, setup_observability  # noqa: E402

_definitions: dict[str, dict[str, Any]] = {}


class CounterDefinition(BaseModel):
    tenant_id: str = Field(min_length=1, max_length=128)
    definition_id: str = Field(min_length=1, max_length=128)
    version: int = Field(ge=1)
    windows: list[str] = Field(min_length=1)
    fields: list[str] = Field(default_factory=list)
    retention_seconds: int = Field(default=2_592_000, ge=300)


class CounterQueryRequest(BaseModel):
    tenant_id: str
    entity_id: str
    payload: dict[str, Any] = Field(default_factory=dict)


class CounterRecordAndQueryRequest(BaseModel):
    tenant_id: str
    entity_id: str
    event_id: str | None = None
    ts: float | None = None
    payload: dict[str, Any] = Field(default_factory=dict)


class CounterReplayEvent(BaseModel):
    tenant_id: str
    entity_id: str
    event_id: str | None = None
    ts: float | None = None
    payload: dict[str, Any] = Field(default_factory=dict)


class CounterReplayRequest(BaseModel):
    scratch_redis_url: str = Field(min_length=8)
    events: list[CounterReplayEvent] = Field(default_factory=list)


class CounterParityRequest(BaseModel):
    tenant_id: str
    entity_id: str
    payload: dict[str, Any] = Field(default_factory=dict)
    expected: dict[str, float] = Field(default_factory=dict)
    epsilon: float = Field(default=0.5, ge=0.0)


def _key(tenant_id: str, definition_id: str) -> str:
    return f"{tenant_id}:{definition_id}"


def _active_def_for_tenant(tenant_id: str) -> dict[str, Any] | None:
    # Keep runtime deterministic: latest definition by version wins.
    candidates = [d for d in _definitions.values() if d.get("tenant_id") == tenant_id]
    if not candidates:
        return None
    candidates.sort(key=lambda d: int(d.get("version", 0)), reverse=True)
    return candidates[0]


app = FastAPI(
    title="Tarka Counter Service",
    version="1.0.0",
    dependencies=[Depends(require_api_key)],
)
if os.environ.get("TARKA_SIGNAL_PLANE_SUBAPP", "").strip() != "1":
    setup_observability(app, "counter-service")


@app.on_event("startup")
async def _startup():
    app.state.redis = None
    app.state.store = None
    redis_url = (
        os.environ.get("COUNTER_SERVICE_REDIS_URL") or os.environ.get("REDIS_URL") or ""
    ).strip()
    if redis_url:
        try:
            rc = aioredis.from_url(redis_url, decode_responses=True)
            app.state.redis = rc
            app.state.store = AggregateStore(rc)
        except Exception:
            app.state.redis = None
            app.state.store = None


@app.on_event("shutdown")
async def _shutdown():
    rc = getattr(app.state, "redis", None)
    if rc is not None:
        await rc.aclose()


@app.get("/v1/health")
async def health():
    return {"status": "ok", "redis_configured": getattr(app.state, "store", None) is not None}


@app.get("/v1/slo")
async def slo():
    return {
        "service": "counter-service",
        "availability_target_pct": 99.9,
        "latency_target_ms_p95": 120,
        "error_budget_window_days": 30,
        "current": {
            **get_metrics().request_count_summary(),
            "redis_configured": getattr(app.state, "store", None) is not None,
        },
    }


@app.get("/v1/definitions")
async def list_definitions():
    return {"items": list(_definitions.values())}


@app.post("/v1/definitions", status_code=201)
async def put_definition(body: CounterDefinition):
    d = body.model_dump()
    _definitions[_key(body.tenant_id, body.definition_id)] = d
    return d


@app.post("/v1/query")
async def query_counters(body: CounterQueryRequest):
    store: AggregateStore | None = getattr(app.state, "store", None)
    if not store:
        raise HTTPException(503, "Redis not configured for counter service")
    counters = await store.compute_features(body.tenant_id, body.entity_id, dict(body.payload))
    active_def = _active_def_for_tenant(body.tenant_id)
    return {
        "tenant_id": body.tenant_id,
        "entity_id": body.entity_id,
        "counters": counters,
        "counter_key_order": list(normalized_velocity_key_names()),
        "definition_id": active_def.get("definition_id") if active_def else None,
        "definition_version": int(active_def.get("version")) if active_def else None,
    }


@app.post("/v1/record-and-query")
async def record_and_query(body: CounterRecordAndQueryRequest):
    store: AggregateStore | None = getattr(app.state, "store", None)
    if not store:
        raise HTTPException(503, "Redis not configured for counter service")
    event_id = body.event_id or uuid.uuid4().hex
    await store.record_event(
        body.tenant_id,
        body.entity_id,
        event_id,
        dict(body.payload),
        ts=body.ts,
    )
    queried = await query_counters(
        CounterQueryRequest(
            tenant_id=body.tenant_id,
            entity_id=body.entity_id,
            payload=dict(body.payload),
        )
    )
    return {
        **queried,
        "recorded": True,
        "event_id": event_id,
        "recorded_at": datetime.now(timezone.utc).isoformat(),
    }


@app.post("/v1/replay")
async def replay(body: CounterReplayRequest):
    client = aioredis.from_url(body.scratch_redis_url.strip(), decode_responses=True)
    try:
        store = AggregateStore(client)
        n = 0
        for ev in body.events:
            eid = ev.event_id or uuid.uuid4().hex
            await store.record_event(ev.tenant_id, ev.entity_id, eid, dict(ev.payload), ts=ev.ts)
            n += 1
    finally:
        await client.aclose()
    return {
        "ok": True,
        "recorded": n,
        "scratch_redis_url": body.scratch_redis_url.strip(),
    }


@app.post("/v1/parity-report")
async def parity_report(body: CounterParityRequest):
    queried = await query_counters(
        CounterQueryRequest(
            tenant_id=body.tenant_id,
            entity_id=body.entity_id,
            payload=dict(body.payload),
        )
    )
    counters = queried.get("counters", {})
    eps = float(body.epsilon)
    drift: dict[str, Any] = {}
    ok = True
    for k, exp in body.expected.items():
        try:
            exp_f = float(exp)
        except (TypeError, ValueError):
            ok = False
            drift[k] = {"expected": exp, "live": counters.get(k), "error": "non_numeric_expected"}
            continue
        live = counters.get(k)
        try:
            live_f = float(live) if live is not None else None
        except (TypeError, ValueError):
            live_f = None
        if live_f is None:
            ok = False
            drift[k] = {"expected": exp_f, "live": live, "delta": None}
            continue
        delta = abs(live_f - exp_f)
        if delta > eps:
            ok = False
            drift[k] = {"expected": exp_f, "live": live_f, "delta": delta}
    return {
        "ok": ok,
        "tenant_id": body.tenant_id,
        "entity_id": body.entity_id,
        "epsilon": eps,
        "checked_keys": list(body.expected.keys()),
        "drift": drift,
        "live_sample": {k: counters.get(k) for k in body.expected.keys()},
    }
