"""
Fixed-window velocity counters (1m / 5m / 1h) for device hashes and IPs — Redis pipeline.

Buckets are Unix-epoch aligned (floor(ts/window_seconds)). Counters are **per bucket**; downstream
can sum recent buckets for approximate rolling velocity or read the active bucket only.
"""

from __future__ import annotations

import hashlib
import time
from typing import Any


def _tenant_segment(tenant_id: str | None) -> str:
    t = (tenant_id or "").strip()
    if not t or len(t) > 128 or "\x00" in t:
        return "_"
    return t


def tenant_key_segment(tenant_id: str | None) -> str:
    """Public alias for stable Redis key segments (velocity + session watch)."""
    return _tenant_segment(tenant_id)


def device_hash_token(canvas_fingerprint: str) -> str:
    """Stable short token for Redis keys (SHA-256 hex)."""
    return hashlib.sha256(canvas_fingerprint.strip().encode("utf-8")).hexdigest()


def ip_key_token(ip: str) -> str:
    """Normalize IP for key segment (IPv6 colons → underscores)."""
    s = ip.strip()[:128]
    return s.replace(":", "_")


def velocity_bucket(window_seconds: int, now_unix: int | None = None) -> int:
    ts = int(now_unix if now_unix is not None else time.time())
    return ts // window_seconds


async def run_ingest_pipeline(
    redis_client: Any,
    *,
    stream_key: str,
    payload_bytes: bytes,
    velocity_commands: list[tuple[str, int]],
    session_watch: tuple[str | None, str | None] | None = None,
    telemetry_list_cap: int = 0,
) -> None:
    """
    Single round-trip: ``LPUSH`` stream + velocity ``INCR`` + ``EXPIRE`` per velocity key.

    Optional **session watch**: ``ZADD`` last-seen score + ``INCR`` event counter for SDK heartbeat
    dropoff monitoring (see :mod:`orchestrator.anumana_session_watch`).

    Optional **telemetry list cap** (``telemetry_list_cap > 0``): ``LTRIM 0 cap-1`` in the same
    pipeline so the list can never grow unbounded while the duck sink is down/undeployed.
    Default ``0`` disables trimming (legacy behaviour for callers that drain the list themselves).

    Uses redis.asyncio pipeline (``transaction=False`` — non-atomic batch for lower latency).
    """
    pipe = redis_client.pipeline(transaction=False)
    pipe.lpush(stream_key, payload_bytes)
    if telemetry_list_cap and int(telemetry_list_cap) > 0:
        pipe.ltrim(stream_key, 0, int(telemetry_list_cap) - 1)
    seen_expire: set[str] = set()
    for key, ttl in velocity_commands:
        pipe.incr(key)
        if key not in seen_expire:
            pipe.expire(key, ttl)
            seen_expire.add(key)

    if session_watch is not None:
        tenant_id, session_id = session_watch
        sid = (session_id or "").strip()
        if sid:
            from anumana_session_watch import (
                session_event_count_key,
                session_watch_member,
                session_watch_zset_key,
            )

            member = session_watch_member(tenant_id, sid)
            pipe.zadd(session_watch_zset_key(), {member: time.time()})
            pipe.incr(session_event_count_key(member))

    await pipe.execute()
