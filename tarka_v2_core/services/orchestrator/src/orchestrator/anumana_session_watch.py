"""
SDK session **heartbeat watch**: track last telemetry time per ``device_session_id`` in Redis.

Ingest updates a sorted set (score = Unix time of last packet). The heartbeat worker scans for sessions
whose last score is older than a silence threshold and, if enough packets were seen (**mid-session**),
sets a string flag value ``HIGH_RISK_DROPOFF`` on a dedicated Redis key.

Environment:

* ``ANUMANA_SESSION_WATCH_ZSET`` — sorted set key (default ``anumana:session_watch``).
* ``ANUMANA_SESSION_EVT_PREFIX`` — prefix for per-session **INCR** event counters (default ``anumana:session_evt``).
* ``ANUMANA_SESSION_RISK_KEY_PREFIX`` — prefix for ``SET`` flags (default ``anumana:session_risk``).
"""

from __future__ import annotations

import logging
import os
import time
from typing import Any

from orchestrator.anumana_velocity import tenant_key_segment

logger = logging.getLogger(__name__)

# Unit separator — ``device_session_id`` allows ``:`` so we cannot split on ``:`` alone.
_MEMBER_SEP = "\x1f"


def session_watch_member(tenant_id: str | None, device_session_id: str) -> str:
    """Stable Redis member id: ``{tenant_segment}\\x1f{session_id}``."""
    t = tenant_key_segment(tenant_id)
    s = device_session_id.strip()
    return f"{t}{_MEMBER_SEP}{s}"


def session_watch_zset_key() -> str:
    return (os.environ.get("ANUMANA_SESSION_WATCH_ZSET") or "anumana:session_watch").strip()


def session_event_count_key(member: str) -> str:
    prefix = (os.environ.get("ANUMANA_SESSION_EVT_PREFIX") or "anumana:session_evt").strip()
    return f"{prefix}:{member}"


def session_risk_flag_key(member: str) -> str:
    prefix = (os.environ.get("ANUMANA_SESSION_RISK_KEY_PREFIX") or "anumana:session_risk").strip()
    return f"{prefix}:{member}"


_RISK_VALUE = "HIGH_RISK_DROPOFF"


async def scan_stale_sessions_for_dropoff(
    redis_client: Any,
    *,
    silence_sec: float,
    min_events: int,
    flag_ttl_sec: int,
    batch_limit: int = 500,
) -> dict[str, int]:
    """
    Find sessions with last activity older than ``silence_sec``. If event count ≥ ``min_events``,
    ``SET`` risk key to ``HIGH_RISK_DROPOFF`` and remove the session from the watch zset.

    Sessions with fewer events are removed from the watch set without flagging (single-beacon noise).
    """
    now = time.time()
    cutoff = now - float(silence_sec)
    zkey = session_watch_zset_key()

    members_raw = await redis_client.zrangebyscore(
        zkey,
        "-inf",
        cutoff,
        start=0,
        num=max(1, min(int(batch_limit), 10_000)),
    )

    flagged = 0
    cleared_young = 0

    for raw_m in members_raw:
        m = raw_m.decode("utf-8") if isinstance(raw_m, bytes) else str(raw_m)

        evt_key = session_event_count_key(m)
        raw_cnt = await redis_client.get(evt_key)
        if raw_cnt is None:
            cnt = 0
        elif isinstance(raw_cnt, bytes):
            cnt = int(raw_cnt.decode("ascii"))
        else:
            cnt = int(raw_cnt)

        risk_key = session_risk_flag_key(m)

        if cnt >= max(1, int(min_events)):
            pipe = redis_client.pipeline(transaction=False)
            ex = int(flag_ttl_sec) if int(flag_ttl_sec) > 0 else None
            if ex is not None:
                pipe.set(risk_key, _RISK_VALUE, ex=ex)
            else:
                pipe.set(risk_key, _RISK_VALUE)
            pipe.zrem(zkey, m)
            pipe.delete(evt_key)
            await pipe.execute()
            flagged += 1
            logger.info(
                "sdk_heartbeat_dropoff_flagged member=%s events=%s risk_key=%s",
                m,
                cnt,
                risk_key,
            )
        else:
            pipe_y = redis_client.pipeline(transaction=False)
            pipe_y.zrem(zkey, m)
            pipe_y.delete(evt_key)
            await pipe_y.execute()
            cleared_young += 1

    return {"scanned": len(members_raw), "flagged": flagged, "cleared_young": cleared_young}
