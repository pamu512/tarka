"""Internal counter manifest + optional scratch-Redis replay (ops / parity)."""

from __future__ import annotations

import os
import uuid
from typing import Any

import redis.asyncio as aioredis
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from decision_api.aggregates import AggregateStore
from decision_api.config import settings
from decision_api.counter_manifest import load_counter_manifest_v1, manifest_version

router = APIRouter(prefix="/v1/internal/counters", tags=["internal-counters"])

MAX_REPLAY_EVENTS = 2000


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
