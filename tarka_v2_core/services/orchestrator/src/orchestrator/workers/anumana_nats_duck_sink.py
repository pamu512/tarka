"""
Batch **SDK telemetry** from Redis (Anumana LPUSH list) into the configured **analytics plane**.

The concrete backend is selected by :envvar:`ENVIRONMENT` (see :func:`~orchestrator.analytics.factory.build_analytics_provider`):
**LocalAnalytics** (DuckDB) in local/demo, **CloudAnalytics** (ClickHouse) in production/staging.

* **NATS** (optional): subscribe to ``ANUMANA_SINK_NATS_SUBJECT`` (default ``tarka.anumana.drain``) with a
  **queue group** so multiple replicas share work; message body optional JSON ``{"max": 200}``.
* **Idle poll**: every ``ANUMANA_SINK_IDLE_POLL_SECONDS`` also drains up to ``ANUMANA_SINK_BATCH_MAX`` so the
  sink progresses without NATS heartbeats.

Run::

    NATS_URL=nats://127.0.0.1:4222 ANUMANA_REDIS_URL=redis://127.0.0.1:6379 \\
      python -m orchestrator.workers.anumana_nats_duck_sink
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import signal
import sys
from typing import Any

from orchestrator.analytics.factory import build_analytics_provider
from orchestrator.analytics.provider import AnalyticsProvider
from orchestrator.workers.sdk_envelope_duck import envelope_bytes_to_transaction

logger = logging.getLogger(__name__)


async def rpop_many(redis_client: Any, key: str, max_items: int) -> list[bytes]:
    out: list[bytes] = []
    for _ in range(max_items):
        raw = await redis_client.rpop(key)
        if raw is None:
            break
        out.append(raw)
    return out


def _append_batch_sync(analytics: AnalyticsProvider, rows: list[bytes]) -> tuple[int, int]:
    ok = 0
    bad = 0
    for raw in rows:
        try:
            txn = envelope_bytes_to_transaction(raw)
            analytics.append_transaction(txn)
            ok += 1
        except Exception:
            logger.exception("anumana_sink_row_dropped")
            bad += 1
    return ok, bad


async def flush_redis_to_analytics(
    redis_client: Any,
    analytics: AnalyticsProvider,
    *,
    redis_key: str,
    max_items: int,
) -> dict[str, int]:
    rows = await rpop_many(redis_client, redis_key, max_items)
    if not rows:
        return {"popped": 0, "written": 0, "dropped": 0}
    written, dropped = await asyncio.to_thread(_append_batch_sync, analytics, rows)
    return {"popped": len(rows), "written": written, "dropped": dropped}


async def run_worker() -> None:
    redis_url = (
        os.environ.get("ANUMANA_TELEMETRY_REDIS_URL") or os.environ.get("ANUMANA_REDIS_URL") or ""
    ).strip()
    redis_key = (
        os.environ.get("ANUMANA_TELEMETRY_REDIS_KEY") or "anumana:browser_telemetry"
    ).strip()
    batch_max = max(1, min(int(os.environ.get("ANUMANA_SINK_BATCH_MAX", "500")), 50_000))
    idle_sec = max(0.5, float(os.environ.get("ANUMANA_SINK_IDLE_POLL_SECONDS", "10")))
    nats_url = (os.environ.get("NATS_URL") or "").strip()
    subject = (os.environ.get("ANUMANA_SINK_NATS_SUBJECT") or "tarka.anumana.drain").strip()
    queue = (os.environ.get("ANUMANA_SINK_NATS_QUEUE") or "duck-analytics-sink").strip()

    if not redis_url:
        raise RuntimeError(
            "Set ANUMANA_TELEMETRY_REDIS_URL or ANUMANA_REDIS_URL to the Redis used by POST /ingest",
        )

    import redis.asyncio as redis_mod

    redis_client = redis_mod.from_url(redis_url, decode_responses=False)
    analytics = build_analytics_provider()

    async def do_flush(max_n: int) -> None:
        stats = await flush_redis_to_analytics(
            redis_client,
            analytics,
            redis_key=redis_key,
            max_items=max_n,
        )
        if stats["popped"]:
            logger.info("anumana_duck_sink_flush %s key=%s", stats, redis_key)

    nc: Any = None
    sub: Any = None
    if nats_url:
        import nats  # noqa: PLC0415 — installed via ``pip install tarka-orchestrator[worker]``

        nc = await nats.connect(nats_url)

        async def _on_msg(msg: Any) -> None:
            max_n = batch_max
            try:
                if msg.data:
                    payload = json.loads(msg.data.decode())
                    if isinstance(payload, dict) and payload.get("max") is not None:
                        max_n = max(1, min(int(payload["max"]), 50_000))
            except Exception:
                pass
            await do_flush(max_n)

        sub = await nc.subscribe(subject, queue=queue, cb=_on_msg)
        logger.info(
            "anumana_duck_sink_nats_connected subject=%s queue=%s",
            subject,
            queue,
        )
    else:
        logger.warning(
            "anumana_duck_sink_nats_disabled NATS_URL unset — idle polling only (%ss)",
            idle_sec,
        )

    stop = asyncio.Event()

    def _request_stop() -> None:
        stop.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _request_stop)
        except NotImplementedError:
            pass

    async def idle_loop() -> None:
        while not stop.is_set():
            try:
                await asyncio.wait_for(stop.wait(), timeout=idle_sec)
                return
            except TimeoutError:
                await do_flush(batch_max)

    idle_task = asyncio.create_task(idle_loop())

    try:
        await stop.wait()
    finally:
        idle_task.cancel()
        try:
            await idle_task
        except asyncio.CancelledError:
            pass
        try:
            stats = await flush_redis_to_analytics(
                redis_client,
                analytics,
                redis_key=redis_key,
                max_items=batch_max,
            )
            if stats["popped"]:
                logger.info("anumana_duck_sink_shutdown_flush %s key=%s", stats, redis_key)
        except Exception:
            logger.exception("anumana_duck_sink_shutdown_flush_failed")
        if sub is not None:
            await sub.unsubscribe()
        if nc is not None:
            await nc.drain()
            await nc.close()
        await redis_client.aclose()
        try:
            analytics.close()
        except Exception:
            logger.exception("anumana_analytics_sink_close_failed")


def main(argv: list[str] | None = None) -> None:
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO"),
        format="%(levelname)s %(name)s %(message)s",
        stream=sys.stderr,
    )
    parser = argparse.ArgumentParser(
        description="Redis → analytics plane sink with optional NATS triggers."
    )
    parser.parse_args(argv)
    try:
        asyncio.run(run_worker())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
