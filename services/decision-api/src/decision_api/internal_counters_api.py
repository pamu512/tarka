"""Internal counter manifest + optional scratch-Redis replay (ops / parity)."""

from __future__ import annotations

import os
import uuid
from typing import Any

import redis.asyncio as aioredis
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from decision_api.aggregates import AggregateStore
from decision_api.config import settings
from decision_api.counter_manifest import load_counter_manifest_v1, manifest_version
from decision_api.db import get_session
from decision_api.models import AuditRecord

router = APIRouter(prefix="/v1/internal/counters", tags=["internal-counters"])

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


async def require_counter_replay_token(request: Request) -> None:
    tok = settings.counter_replay_token.strip()
    if not tok:
        raise HTTPException(
            status_code=503,
            detail="counter replay disabled — set COUNTER_REPLAY_TOKEN in the environment",
        )
    if request.headers.get("x-tarka-counter-replay-token", "") != tok:
        raise HTTPException(status_code=401, detail="invalid or missing X-Tarka-Counter-Replay-Token")


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


@router.post("/replay", dependencies=[Depends(require_counter_replay_token)])
async def post_counter_replay(body: CounterReplayRequest) -> dict[str, Any]:
    """
    Replay JSON events into a scratch Redis using AggregateStore (offline parity).

    Requires header ``X-Tarka-Counter-Replay-Token`` matching ``COUNTER_REPLAY_TOKEN``.
    """
    client = aioredis.from_url(body.scratch_redis_url.strip(), decode_responses=True)
    try:
        store = AggregateStore(client)
        recorded = await apply_replay_events(store, body.events)
    finally:
        await client.aclose()

    return {
        "manifest_version": manifest_version(),
        "recorded": recorded,
        "scratch_redis_url": body.scratch_redis_url.strip(),
    }


@router.post("/replay/from-audit", dependencies=[Depends(require_counter_replay_token)])
async def post_counter_replay_from_audit(
    body: CounterReplayFromAuditRequest,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """
    Load recent ``decision_audit`` rows for (tenant_id, entity_id), map ``payload_snapshot.payload``
    to aggregate ``fields``, and replay into scratch Redis (same as ``POST /replay`` but sourced from DB).
    """
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

    return {
        "manifest_version": manifest_version(),
        "recorded": recorded,
        "audit_rows": len(rows),
        "scratch_redis_url": body.scratch_redis_url.strip(),
        "tenant_id": body.tenant_id.strip(),
        "entity_id": body.entity_id.strip(),
    }
