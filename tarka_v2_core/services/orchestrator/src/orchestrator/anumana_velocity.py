"""
Fixed-window velocity counters (1m / 5m / 1h) for device hashes and IPs — Redis pipeline.

Buckets are Unix-epoch aligned (floor(ts/window_seconds)). Counters are **per bucket**; downstream
can sum recent buckets for approximate rolling velocity or read the active bucket only.
"""

from __future__ import annotations

import hashlib
import os
import time
from dataclasses import dataclass
from typing import Any

WINDOW_SPECS: tuple[tuple[str, int, int], ...] = (
    ("1m", 60, int(os.environ.get("ANUMANA_VEL_TTL_1M_SEC", "180"))),
    ("5m", 300, int(os.environ.get("ANUMANA_VEL_TTL_5M_SEC", "900"))),
    ("1h", 3600, int(os.environ.get("ANUMANA_VEL_TTL_1H_SEC", "7200"))),
)


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


def velocity_key_prefix() -> str:
    return (
        os.environ.get("ANUMANA_VELOCITY_KEY_PREFIX") or "anumana:velocity"
    ).strip() or "anumana:velocity"


def build_velocity_incr_expire_commands(
    *,
    tenant_id: str | None,
    device_token: str | None,
    ip_tokens: list[str],
    now_unix: int | None = None,
) -> list[tuple[str, int]]:
    """
    Return list of ``(redis_key, ttl_sec)`` for each velocity bucket to ``INCR`` + ``EXPIRE``.

    ``ip_tokens`` should be deduplicated non-empty ingress / client IP key segments.
    """
    prefix = velocity_key_prefix()
    tseg = _tenant_segment(tenant_id)
    now = int(now_unix if now_unix is not None else time.time())
    out: list[tuple[str, int]] = []

    for win_label, win_sec, ttl in WINDOW_SPECS:
        bucket = velocity_bucket(win_sec, now)
        if device_token:
            key = f"{prefix}:t:{tseg}:device:{win_label}:{device_token}:{bucket}"
            out.append((key, ttl))
        for ip_tok in ip_tokens:
            if not ip_tok:
                continue
            key = f"{prefix}:t:{tseg}:ip:{win_label}:{ip_tok}:{bucket}"
            out.append((key, ttl))

    return out


@dataclass(frozen=True, slots=True)
class TransactionVelocityCommand:
    """One Redis ``INCRBY`` (+ ``EXPIRE``) and matching ClickHouse counter increment."""

    redis_key: str
    ttl_sec: int
    increment: int


def build_transaction_velocity_incrby_commands(
    *,
    tenant_id: str | None,
    device_token: str | None,
    ip_tokens: list[str],
    amount_cents: int,
    now_unix: int | None = None,
) -> list[TransactionVelocityCommand]:
    """
    Build transaction velocity increments using the production ``anumana:velocity`` namespace.

    Each device/IP/window/bucket gets:
      - count key (``…:{bucket}``) — ``INCRBY`` +1
      - amount key (``…:{bucket}:amt``) — ``INCRBY`` ``amount_cents``
    """
    if amount_cents < 0:
        raise ValueError(f"amount_cents must be >= 0, got {amount_cents}")
    amount_incr = int(amount_cents)

    prefix = velocity_key_prefix()
    tseg = _tenant_segment(tenant_id)
    now = int(now_unix if now_unix is not None else time.time())
    out: list[TransactionVelocityCommand] = []

    for win_label, win_sec, ttl in WINDOW_SPECS:
        bucket = velocity_bucket(win_sec, now)
        if device_token:
            count_key = f"{prefix}:t:{tseg}:device:{win_label}:{device_token}:{bucket}"
            out.append(TransactionVelocityCommand(count_key, ttl, 1))
            out.append(TransactionVelocityCommand(f"{count_key}:amt", ttl, amount_incr))
        for ip_tok in ip_tokens:
            if not ip_tok:
                continue
            count_key = f"{prefix}:t:{tseg}:ip:{win_label}:{ip_tok}:{bucket}"
            out.append(TransactionVelocityCommand(count_key, ttl, 1))
            out.append(TransactionVelocityCommand(f"{count_key}:amt", ttl, amount_incr))

    return out


async def apply_velocity_incrby_multi_exec(
    redis_client: Any,
    commands: list[TransactionVelocityCommand],
) -> None:
    """Apply velocity ``INCRBY`` + ``EXPIRE`` inside a Redis ``MULTI/EXEC`` block."""
    if not commands:
        return
    pipe = redis_client.pipeline(transaction=True)
    seen_expire: set[str] = set()
    for cmd in commands:
        pipe.incrby(cmd.redis_key, cmd.increment)
        if cmd.redis_key not in seen_expire:
            pipe.expire(cmd.redis_key, cmd.ttl_sec)
            seen_expire.add(cmd.redis_key)
    await pipe.execute()


async def run_ingest_pipeline(
    redis_client: Any,
    *,
    stream_key: str,
    payload_bytes: bytes,
    velocity_commands: list[tuple[str, int]],
    session_watch: tuple[str | None, str | None] | None = None,
) -> None:
    """
    Single round-trip: ``LPUSH`` stream + velocity ``INCR`` + ``EXPIRE`` per velocity key.

    Optional **session watch**: ``ZADD`` last-seen score + ``INCR`` event counter for SDK heartbeat
    dropoff monitoring (see :mod:`orchestrator.anumana_session_watch`).

    Uses redis.asyncio pipeline (``transaction=False`` — non-atomic batch for lower latency).
    """
    pipe = redis_client.pipeline(transaction=False)
    pipe.lpush(stream_key, payload_bytes)
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
            from orchestrator.anumana_session_watch import (
                session_event_count_key,
                session_watch_member,
                session_watch_zset_key,
            )

            member = session_watch_member(tenant_id, sid)
            pipe.zadd(session_watch_zset_key(), {member: time.time()})
            pipe.incr(session_event_count_key(member))

    await pipe.execute()
