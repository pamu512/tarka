"""
SDK **heartbeat** + **tab-close dropoff** (Redis).

* **Ping** (≈ every 30s from the SDK): refresh last-seen in a sorted set.
* **Logout** / **submit**: remove the session from the watch set so we never raise a false dropoff.
* **Monitor** (periodic): sessions with no ping for ``SIGNAL_HEARTBEAT_STALE_AFTER_SEC`` (default **45**,
  i.e. one missed 30s window + margin) and no terminal event → ``SET session:{session_id}:dropoff 1 EX 300``.

The **Orchestrator** (or any service sharing the same Redis) can read::

    GET session:{uuid}:dropoff
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field
from redis.asyncio import Redis

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Heartbeat"])

_DEFAULT_WATCH_ZSET = "signal:heartbeat:watch"
_DEFAULT_STALE_SEC = 45.0
_DEFAULT_DROPOFF_TTL = 300


def _watch_zset_key() -> str:
    return (os.environ.get("SIGNAL_HEARTBEAT_WATCH_ZSET") or _DEFAULT_WATCH_ZSET).strip()


def dropoff_flag_key(session_id: str) -> str:
    """Redis key the Orchestrator reads (``session:{id}:dropoff``)."""
    sid = session_id.strip()
    return f"session:{sid}:dropoff"


def terminal_marker_key(session_id: str) -> str:
    """Optional marker (logout/submit) to suppress dropoff if a tick races the ZREM."""
    return f"session:{session_id.strip()}:terminal"


def stale_after_sec() -> float:
    raw = os.environ.get("SIGNAL_HEARTBEAT_STALE_AFTER_SEC", "").strip()
    if not raw:
        return _DEFAULT_STALE_SEC
    return max(35.0, min(float(raw), 600.0))


def dropoff_ttl_sec() -> int:
    raw = os.environ.get("SIGNAL_HEARTBEAT_DROPOFF_TTL_SEC", "").strip()
    if not raw:
        return _DEFAULT_DROPOFF_TTL
    return max(60, min(int(raw), 86_400))


class HeartbeatPingBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: UUID


class HeartbeatSessionBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: UUID


async def get_redis(request: Request) -> Redis:
    r = getattr(request.app.state, "redis", None)
    if r is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"error": "redis_unavailable"},
        )
    return r


async def register_ping(redis: Redis, session_id: UUID) -> None:
    zkey = _watch_zset_key()
    sid = str(session_id)
    now = time.time()
    pipe = redis.pipeline(transaction=False)
    pipe.zadd(zkey, {sid: now})
    pipe.delete(dropoff_flag_key(sid))
    pipe.delete(terminal_marker_key(sid))
    await pipe.execute()


async def register_terminal(redis: Redis, session_id: UUID, kind: str) -> None:
    """``kind`` is ``logout`` or ``submit``."""
    zkey = _watch_zset_key()
    sid = str(session_id)
    pipe = redis.pipeline(transaction=False)
    pipe.zrem(zkey, sid)
    pipe.set(terminal_marker_key(sid), kind, ex=3600)
    pipe.delete(dropoff_flag_key(sid))
    await pipe.execute()


async def scan_stale_sessions_for_dropoff(redis: Redis) -> dict[str, int]:
    """
    Flag tab-close / silent dropoff: stale ZSET members → ``session:{id}:dropoff`` (5-minute TTL default).
    """
    zkey = _watch_zset_key()
    cutoff = time.time() - stale_after_sec()
    members = await redis.zrangebyscore(zkey, "-inf", cutoff, start=0, num=10_000)
    flagged = 0
    for raw in members:
        sid = raw.decode("utf-8") if isinstance(raw, bytes) else str(raw)
        term = await redis.get(terminal_marker_key(sid))
        if term is not None:
            await redis.zrem(zkey, sid)
            continue
        ex = dropoff_ttl_sec()
        pipe = redis.pipeline(transaction=False)
        pipe.set(dropoff_flag_key(sid), "1", ex=ex)
        pipe.zrem(zkey, sid)
        await pipe.execute()
        flagged += 1
        logger.info("heartbeat_dropoff_flagged session_id=%s ttl_sec=%s", sid, ex)
    return {"scanned": len(members), "flagged": flagged}


@router.post("/ping", status_code=status.HTTP_204_NO_CONTENT)
async def heartbeat_ping(
    body: HeartbeatPingBody,
    redis: Annotated[Redis, Depends(get_redis)],
) -> None:
    """Lightweight SDK ping (~ every 30s)."""
    await register_ping(redis, body.session_id)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def heartbeat_logout(
    body: HeartbeatSessionBody,
    redis: Annotated[Redis, Depends(get_redis)],
) -> None:
    await register_terminal(redis, body.session_id, "logout")


@router.post("/submit", status_code=status.HTTP_204_NO_CONTENT)
async def heartbeat_submit(
    body: HeartbeatSessionBody,
    redis: Annotated[Redis, Depends(get_redis)],
) -> None:
    await register_terminal(redis, body.session_id, "submit")


async def run_heartbeat_monitor(*, stop: asyncio.Event | None = None) -> None:
    """
    Background loop: call :func:`scan_stale_sessions_for_dropoff` on an interval.

    Env: ``SIGNAL_HEARTBEAT_REDIS_URL`` or ``SIGNAL_REDIS_URL`` / ``REDIS_URL``; interval
    ``SIGNAL_HEARTBEAT_MONITOR_INTERVAL_SEC`` (default **10**).
    """
    import redis.asyncio as redis_mod

    url = (
        os.environ.get("SIGNAL_HEARTBEAT_REDIS_URL")
        or os.environ.get("SIGNAL_REDIS_URL")
        or os.environ.get("REDIS_URL")
        or ""
    ).strip()
    if not url:
        raise RuntimeError(
            "Set SIGNAL_HEARTBEAT_REDIS_URL, SIGNAL_REDIS_URL, or REDIS_URL for the heartbeat monitor",
        )
    interval = max(2.0, float(os.environ.get("SIGNAL_HEARTBEAT_MONITOR_INTERVAL_SEC", "10")))
    redis = redis_mod.from_url(url, decode_responses=True)
    stop_ev = stop or asyncio.Event()

    try:
        while not stop_ev.is_set():
            try:
                stats = await scan_stale_sessions_for_dropoff(redis)
                if stats["flagged"]:
                    logger.info("heartbeat_monitor_tick %s", stats)
            except Exception:
                logger.exception("heartbeat_monitor_tick_failed")
            try:
                await asyncio.wait_for(stop_ev.wait(), timeout=interval)
                break
            except TimeoutError:
                pass
    finally:
        await redis.aclose()


def monitor_main() -> None:
    """CLI entry for ``python -m signal_api.heartbeat`` (monitor only)."""
    import argparse
    import signal
    import sys

    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO"),
        format="%(levelname)s %(name)s %(message)s",
        stream=sys.stderr,
    )
    parser = argparse.ArgumentParser(description="Redis SDK heartbeat dropoff monitor.")
    parser.parse_args()
    stop = asyncio.Event()

    def _sig() -> None:
        stop.set()

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _sig)
        except NotImplementedError:
            pass
    try:
        loop.run_until_complete(run_heartbeat_monitor(stop=stop))
    except KeyboardInterrupt:
        pass
    finally:
        loop.close()


if __name__ == "__main__":
    monitor_main()
