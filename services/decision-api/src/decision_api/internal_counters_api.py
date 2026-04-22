from __future__ import annotations
import json
import os
import uuid
from pathlib import Path
from typing import Any

import redis.asyncio as aioredis
from fastapi import APIRouter, Depends, HTTPException, Security
from fastapi.security import APIKeyHeader
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from decision_api.aggregates import AggregateStore
from decision_api.config import settings
from decision_api.counter_manifest import load_counter_manifest_v1, manifest_version
from decision_api.db import get_session
from decision_api.models import AuditRecord

"""Internal counter manifest + optional scratch-Redis replay (ops / parity)."""
router = APIRouter(prefix="/v1/internal/counters", tags=["internal-counters"])

# OpenAPI + runtime: header-based token (same as env COUNTER_REPLAY_TOKEN)
_counter_replay_api_key = APIKeyHeader(
    name="X-Tarka-Counter-Replay-Token",
    auto_error=False,
    scheme_name="TarkaCounterReplayToken",
)

MAX_REPLAY_EVENTS = 2000
MAX_REPLAY_FROM_AUDIT = 20_000


class ReplayEventIn(BaseModel):
    tenant_id: str = Field(min_length=1, max_length=256)
    entity_id: str = Field(min_length=1, max_length=512)
    event_id: str | None = Field(default=None, max_length=256)
    fields: dict[str, Any] = Field(default_factory=dict)
    ts: float | None = None


class CounterReplayRequest(BaseModel):
    """Replay events into a scratch Redis (isolated DB index recommended)."""

    scratch_redis_url: str = Field(min_length=8, description="e.g. redis://localhost:6379/15")
    events: list[ReplayEventIn] = Field(default_factory=list, max_length=MAX_REPLAY_EVENTS)


class CounterReplayFromAuditRequest(BaseModel):
    """Replay aggregates from stored audit rows (payload → counter fields) into scratch Redis."""

    scratch_redis_url: str = Field(min_length=8, description="e.g. redis://localhost:6379/15")
    tenant_id: str = Field(min_length=1, max_length=128)
    entity_id: str = Field(min_length=1, max_length=512)
    limit: int = Field(default=2000, ge=1, le=MAX_REPLAY_FROM_AUDIT)


class CounterReplayResponse(BaseModel):
    """Result of replaying inline events into scratch Redis."""

    manifest_version: str
    recorded: int = Field(ge=0)
    scratch_redis_url: str


class CounterReplayFromAuditResponse(BaseModel):
    """Result of replaying audit rows into scratch Redis."""

    manifest_version: str
    recorded: int = Field(ge=0)
    audit_rows: int = Field(ge=0)
    scratch_redis_url: str
    tenant_id: str
    entity_id: str


async def require_counter_replay_token(
    token: str | None = Security(_counter_replay_api_key),
) -> None:
    expected = settings.counter_replay_token.strip()
    if not expected:
        raise HTTPException(
            status_code=503,
            detail="counter replay disabled — set COUNTER_REPLAY_TOKEN in the environment",
        )
    if not token or token.strip() != expected:
        raise HTTPException(status_code=401, detail="invalid or missing X-Tarka-Counter-Replay-Token")


# Secured sub-router: token dependency applies to all routes here (merged into main router for OpenAPI)
_secured = APIRouter(dependencies=[Security(require_counter_replay_token)])


def _counter_catalog_path() -> Path:
    return Path(__file__).resolve().parent / "data" / "counter_catalog.json"


def _read_counter_catalog_file() -> dict[str, Any]:
    """Declarative counter catalog (titles, categories) alongside counter_manifest_v1."""
    p = _counter_catalog_path()
    if not p.is_file():
        return {"catalog_version": "0", "counters": [], "note": f"missing {p}"}
    return json.loads(p.read_text(encoding="utf-8"))


async def apply_replay_events(store: AggregateStore, events: list[ReplayEventIn]) -> int:
    n = 0
    for ev in events:
        eid = ev.event_id or uuid.uuid4().hex
        await store.record_event(ev.tenant_id, ev.entity_id, eid, dict(ev.fields), ts=ev.ts)
        n += 1
    return n


@router.get("/manifest")
async def get_counter_manifest() -> dict[str, Any]:
    """Public read: versioned list of aggregate feature outputs (parity contract)."""
    m = dict(load_counter_manifest_v1())
    ver = os.environ.get("AGG_KEY_VERSION", "").strip()
    if ver and all(c.isalnum() or c in "._:-" for c in ver):
        m["redis_key_version"] = ver
    return m


@router.get("/catalog")
async def get_counter_catalog_merged() -> dict[str, Any]:
    """Human-readable counter catalog merged with manifest feature names (ops UI)."""
    manifest = dict(load_counter_manifest_v1())
    cat = _read_counter_catalog_file()
    ver = os.environ.get("AGG_KEY_VERSION", "").strip()
    if ver and all(c.isalnum() or c in "._:-" for c in ver):
        manifest["redis_key_version"] = ver
    by_name = {str(x.get("name", "")): x for x in (cat.get("counters") or []) if isinstance(x, dict)}
    feats = manifest.get("feature_outputs") or []
    merged: list[dict[str, Any]] = []
    for f in feats:
        if not isinstance(f, dict):
            continue
        name = str(f.get("name", "")).strip()
        extra = dict(by_name.get(name, {}))
        merged.append({**f, **{k: v for k, v in extra.items() if k != "name"}})
    return {
        "catalog_version": cat.get("catalog_version", "0"),
        "description": cat.get("description", ""),
        "manifest_version": manifest.get("manifest_version"),
        "redis_key_version": manifest.get("redis_key_version") or ver or None,
        "counters": merged,
    }


@router.get("/definitions")
async def get_counter_definitions() -> dict[str, Any]:
    """Raw declarative counter definitions for internal tooling and docs generation."""
    cat = _read_counter_catalog_file()
    manifest = dict(load_counter_manifest_v1())
    return {
        "catalog_version": cat.get("catalog_version", "0"),
        "manifest_version": manifest.get("manifest_version"),
        "definitions": cat.get("counters") or [],
    }


@_secured.post(
    "/replay",
    response_model=CounterReplayResponse,
    summary="Replay inline events into scratch Redis",
    description=(
        "Replay JSON events into a scratch Redis using AggregateStore (offline parity). "
        "Requires header **X-Tarka-Counter-Replay-Token** matching **COUNTER_REPLAY_TOKEN**. "
        "Aggregate keys honor **AGG_KEY_VERSION** when set on this process."
    ),
    responses={
        401: {"description": "Invalid or missing replay token"},
        503: {"description": "COUNTER_REPLAY_TOKEN not configured"},
    },
)
async def post_counter_replay(body: CounterReplayRequest) -> CounterReplayResponse:
    client = aioredis.from_url(body.scratch_redis_url.strip(), decode_responses=True)
    try:
        store = AggregateStore(client)
        recorded = await apply_replay_events(store, body.events)
    finally:
        await client.aclose()

    return CounterReplayResponse(
        manifest_version=manifest_version(),
        recorded=recorded,
        scratch_redis_url=body.scratch_redis_url.strip(),
    )


@_secured.post(
    "/replay/from-audit",
    response_model=CounterReplayFromAuditResponse,
    summary="Replay decision_audit rows into scratch Redis",
    description=(
        "Load recent **decision_audit** rows for (tenant_id, entity_id); map **payload_snapshot.payload** "
        "to aggregate fields. Same authentication as **POST /replay**."
    ),
    responses={
        401: {"description": "Invalid or missing replay token"},
        404: {"description": "No audit rows for tenant_id and entity_id"},
        503: {"description": "COUNTER_REPLAY_TOKEN not configured"},
    },
)
async def post_counter_replay_from_audit(
    body: CounterReplayFromAuditRequest,
    session: AsyncSession = Depends(get_session),
) -> CounterReplayFromAuditResponse:
    stmt = (
        select(AuditRecord)
        .where(
            AuditRecord.tenant_id == body.tenant_id.strip(),
            AuditRecord.entity_id == body.entity_id.strip(),
        )
        .order_by(AuditRecord.created_at.asc())
        .limit(body.limit)
    )
    result = await session.execute(stmt)
    rows = result.scalars().all()
    if not rows:
        raise HTTPException(
            status_code=404,
            detail=f"no audit rows for tenant_id={body.tenant_id!r} entity_id={body.entity_id!r}",
        )

    events_in: list[ReplayEventIn] = []
    for row in rows:
        fields: dict[str, Any] = {}
        snap = row.payload_snapshot
        if isinstance(snap, dict):
            inner = snap.get("payload")
            if isinstance(inner, dict):
                fields = dict(inner)
        ts_f: float | None = None
        if row.created_at is not None:
            ts_f = row.created_at.timestamp()
        events_in.append(
            ReplayEventIn(
                tenant_id=row.tenant_id,
                entity_id=row.entity_id,
                event_id=str(row.trace_id),
                fields=fields,
                ts=ts_f,
            )
        )

    client = aioredis.from_url(body.scratch_redis_url.strip(), decode_responses=True)
    try:
        store = AggregateStore(client)
        recorded = await apply_replay_events(store, events_in)
    finally:
        await client.aclose()

    return CounterReplayFromAuditResponse(
        manifest_version=manifest_version(),
        recorded=recorded,
        audit_rows=len(rows),
        scratch_redis_url=body.scratch_redis_url.strip(),
        tenant_id=body.tenant_id.strip(),
        entity_id=body.entity_id.strip(),
    )


router.include_router(_secured)
