"""
Background worker: scan Redis session watch zset and flag **HIGH_RISK_DROPOFF** when telemetry stops
mid-session (after ``ANUMANA_HEARTBEAT_MIN_EVENTS`` packets, silence ≥ ``ANUMANA_HEARTBEAT_SILENCE_SEC``).

Run::

    ANUMANA_REDIS_URL=redis://127.0.0.1:6379 python -m orchestrator.workers.sdk_heartbeat_monitor
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import signal
import sys
from typing import Any

from orchestrator.anumana_session_watch import scan_stale_sessions_for_dropoff

logger = logging.getLogger(__name__)


async def run_worker() -> None:
    redis_url = (
        os.environ.get("ANUMANA_TELEMETRY_REDIS_URL") or os.environ.get("ANUMANA_REDIS_URL") or ""
    ).strip()
    if not redis_url:
        raise RuntimeError(
            "Set ANUMANA_TELEMETRY_REDIS_URL or ANUMANA_REDIS_URL to the Redis used by POST /ingest",
        )

    interval_sec = max(1.0, float(os.environ.get("ANUMANA_HEARTBEAT_MONITOR_INTERVAL_SEC", "15")))
    silence_sec = max(5.0, float(os.environ.get("ANUMANA_HEARTBEAT_SILENCE_SEC", "120")))
    min_events = max(1, int(os.environ.get("ANUMANA_HEARTBEAT_MIN_EVENTS", "2")))
    flag_ttl_sec = int(os.environ.get("ANUMANA_HEARTBEAT_FLAG_TTL_SEC", "604800"))
    batch_limit = max(1, min(int(os.environ.get("ANUMANA_HEARTBEAT_SCAN_BATCH", "500")), 10_000))

    import redis.asyncio as redis_mod

    redis_client: Any = redis_mod.from_url(redis_url)
    stop = asyncio.Event()

    def _request_stop() -> None:
        stop.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _request_stop)
        except NotImplementedError:
            pass

    try:
        while not stop.is_set():
            try:
                stats = await scan_stale_sessions_for_dropoff(
                    redis_client,
                    silence_sec=silence_sec,
                    min_events=min_events,
                    flag_ttl_sec=flag_ttl_sec,
                    batch_limit=batch_limit,
                )
                if stats["scanned"]:
                    logger.info("sdk_heartbeat_monitor_tick %s", stats)
            except Exception:
                logger.exception("sdk_heartbeat_monitor_tick_failed")
            try:
                await asyncio.wait_for(stop.wait(), timeout=interval_sec)
                break
            except TimeoutError:
                pass
    finally:
        await redis_client.aclose()


def main(argv: list[str] | None = None) -> None:
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO"),
        format="%(levelname)s %(name)s %(message)s",
        stream=sys.stderr,
    )
    parser = argparse.ArgumentParser(
        description="SDK telemetry heartbeat / dropoff monitor (Redis)."
    )
    parser.parse_args(argv)
    try:
        asyncio.run(run_worker())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
