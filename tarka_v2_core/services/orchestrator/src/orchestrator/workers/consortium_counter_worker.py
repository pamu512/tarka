"""
JetStream pull consumer for enriched ``normalized_labels`` on ``tarka.events.labels``.

Updates the global consortium threat-matrix counters in Redis and ClickHouse using atomic
Messages are acked only after both destinations verify successful execution.

Run (requires ``pip install tarka-orchestrator[worker]``)::

    NATS_URL=nats://127.0.0.1:4222 \\
    ANUMANA_REDIS_URL=redis://127.0.0.1:6379 \\
    CLICKHOUSE_HOST=127.0.0.1 \\
      python -m orchestrator.workers.consortium_counter_worker
"""

from __future__ import annotations

import asyncio
import logging
import os
import signal
from typing import Any

from orchestrator.analytics.consortium_threat_matrix import (
    ConsortiumThreatMatrixError,
    apply_consortium_threat_counter_increments,
    apply_consortium_threat_counter_increments_clickhouse,
    build_consortium_threat_counter_commands,
    clickhouse_configured,
    consortium_id_from_environment,
    ensure_consortium_threat_counters_table,
    verify_consortium_threat_counter_increments,
)
from orchestrator.messaging.labels_jetstream import (
    TARKA_LABELS_SUBJECT,
    consortium_labels_durable_name,
    consortium_labels_fetch_batch_size,
    decode_normalized_label_event,
)
from orchestrator.messaging.nats_jetstream import (
    TARKA_EVENTS_STREAM_NAME,
    TarkaEventsJetStreamInitializer,
)

logger = logging.getLogger(__name__)

_NAK_DELAY_SEC = 5


class ConsortiumCounterDeps:
    """Runtime dependencies for the labels JetStream consumer."""

    __slots__ = ("redis_client", "clickhouse_client", "consortium_id")

    def __init__(
        self,
        *,
        redis_client: Any,
        clickhouse_client: Any,
        consortium_id: str | None = None,
    ) -> None:
        self.redis_client = redis_client
        self.clickhouse_client = clickhouse_client
        self.consortium_id = (consortium_id or consortium_id_from_environment()).strip() or "global"


def is_retryable_counter_failure(exc: BaseException) -> bool:
    """True when Redis/ClickHouse counter application should be redelivered."""
    if isinstance(exc, (ConnectionError, TimeoutError, OSError)):
        return True
    if isinstance(exc, ConsortiumThreatMatrixError):
        return False
    if isinstance(exc, RuntimeError):
        message = str(exc).lower()
        if "redis" in message or "clickhouse" in message:
            return True
    return False


async def apply_enriched_label_to_threat_matrix(
    deps: ConsortiumCounterDeps,
    label_entity: dict[str, Any],
) -> bool:
    """
    Apply one enriched label event to Redis + ClickHouse threat-matrix counters.

    Returns ``True`` when counters were incremented, ``False`` when the label was already processed.
    """
    label_id, commands = build_consortium_threat_counter_commands(
        label_entity,
        consortium_id=deps.consortium_id,
    )

    redis_applied = await apply_consortium_threat_counter_increments(
        deps.redis_client,
        commands,
        consortium_id=deps.consortium_id,
        label_id=label_id,
    )
    await verify_consortium_threat_counter_increments(deps.redis_client, commands)

    ch_client = deps.clickhouse_client
    if ch_client is None:
        if clickhouse_configured():
            raise RuntimeError(
                "CLICKHOUSE_HOST/CLICKHOUSE_URL is set but ClickHouse client is unavailable "
                "for consortium threat-matrix counters",
            )
        raise RuntimeError(
            "ClickHouse is required for consortium threat-matrix counters "
            "(set CLICKHOUSE_HOST or CLICKHOUSE_URL)",
        )

    await asyncio.to_thread(
        _apply_clickhouse_threat_increments_sync,
        ch_client,
        commands,
        label_id,
    )

    logger.info(
        "consortium_counter_applied label_id=%s consortium_id=%s command_count=%s redis_applied=%s",
        label_id,
        deps.consortium_id,
        len(commands),
        redis_applied,
    )
    return redis_applied


def _apply_clickhouse_threat_increments_sync(
    client: Any,
    commands: list[Any],
    label_id: str,
) -> None:
    ensure_consortium_threat_counters_table(client)
    apply_consortium_threat_counter_increments_clickhouse(client, commands, label_id=label_id)


async def process_consortium_label_message(deps: ConsortiumCounterDeps, msg: Any) -> None:
    """Decode one JetStream message, update counters, and ``ack`` / ``nak`` explicitly."""
    label_entity = decode_normalized_label_event(msg)
    label_id = str(label_entity.get("id") or "").strip() or None
    try:
        await apply_enriched_label_to_threat_matrix(deps, label_entity)
    except ConsortiumThreatMatrixError as exc:
        logger.warning(
            "consortium_counter_invalid_label label_id=%s error=%s",
            label_id,
            exc,
        )
        await msg.ack()
        return
    except Exception as exc:
        if is_retryable_counter_failure(exc):
            logger.warning(
                "consortium_counter_retryable_failure label_id=%s exc_type=%s",
                label_id,
                type(exc).__name__,
            )
            await msg.nak(delay=_NAK_DELAY_SEC)
            return
        logger.exception(
            "consortium_counter_unrecoverable_failure label_id=%s",
            label_id,
        )
        await msg.ack()
        return

    await msg.ack()


async def run_pull_consumer(
    *,
    deps: ConsortiumCounterDeps,
    js: Any,
    subject: str,
    stop: asyncio.Event,
) -> None:
    """Explicit JetStream fetch loop for ``tarka.events.labels``."""
    import nats.errors  # noqa: PLC0415

    stream_name = TARKA_EVENTS_STREAM_NAME
    durable = consortium_labels_durable_name()
    batch_size = consortium_labels_fetch_batch_size()

    await TarkaEventsJetStreamInitializer.from_environment().ensure_streams_on(js)
    sub = await js.pull_subscribe(subject, durable=durable, stream=stream_name)
    logger.info(
        "consortium_counter_pull_subscribed stream=%s subject=%s durable=%s batch=%s",
        stream_name,
        subject,
        durable,
        batch_size,
    )

    while not stop.is_set():
        try:
            msgs = await sub.fetch(batch=batch_size, timeout=1.0)
        except nats.errors.TimeoutError:
            continue
        except Exception:
            logger.exception("consortium_counter_fetch_failed")
            await asyncio.sleep(1.0)
            continue

        for msg in msgs:
            if stop.is_set():
                break
            await process_consortium_label_message(deps, msg)


async def build_consortium_counter_deps() -> ConsortiumCounterDeps:
    redis_url = (
        (os.environ.get("ANUMANA_TELEMETRY_REDIS_URL") or os.environ.get("ANUMANA_REDIS_URL") or "").strip()
    )
    if not redis_url:
        raise RuntimeError(
            "ANUMANA_REDIS_URL (or ANUMANA_TELEMETRY_REDIS_URL) is required for consortium counter worker",
        )

    import redis.asyncio as redis_mod  # noqa: PLC0415

    redis_client = redis_mod.from_url(redis_url, decode_responses=False)

    from orchestrator.analytics.cloud_provider import _try_connect_clickhouse  # noqa: PLC0415

    clickhouse_client = _try_connect_clickhouse()
    if clickhouse_client is None:
        if clickhouse_configured():
            raise RuntimeError(
                "CLICKHOUSE_HOST/CLICKHOUSE_URL is set but ClickHouse client could not be initialized",
            )
        raise RuntimeError(
            "CLICKHOUSE_HOST or CLICKHOUSE_URL is required for consortium counter worker",
        )

    return ConsortiumCounterDeps(
        redis_client=redis_client,
        clickhouse_client=clickhouse_client,
    )


async def close_consortium_counter_deps(deps: ConsortiumCounterDeps) -> None:
    try:
        await deps.redis_client.aclose()
    except Exception:
        logger.exception("consortium_counter_redis_close_failed")
    if deps.clickhouse_client is not None:
        try:
            close_fn = getattr(deps.clickhouse_client, "close", None)
            if callable(close_fn):
                close_fn()
        except Exception:
            logger.exception("consortium_counter_clickhouse_close_failed")


async def run() -> None:
    nats_url = (os.environ.get("NATS_URL") or "").strip()
    if not nats_url:
        raise RuntimeError("NATS_URL is required")

    try:
        import nats  # noqa: PLC0415
    except ImportError as exc:
        raise RuntimeError(
            "nats-py is required (pip install tarka-orchestrator[worker])",
        ) from exc

    deps = await build_consortium_counter_deps()
    subject = TARKA_LABELS_SUBJECT
    nc = await nats.connect(nats_url)
    js = nc.jetstream()
    if js is None:
        await nc.drain()
        await close_consortium_counter_deps(deps)
        raise RuntimeError("NATS JetStream context is not available on the broker")

    stop = asyncio.Event()

    def _stop() -> None:
        stop.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _stop)
        except NotImplementedError:
            pass

    consumer_task = asyncio.create_task(
        run_pull_consumer(deps=deps, js=js, subject=subject, stop=stop),
    )
    logger.info(
        "consortium_counter_worker_started subject=%s consortium_id=%s",
        subject,
        deps.consortium_id,
    )

    try:
        await stop.wait()
    finally:
        consumer_task.cancel()
        with asyncio.suppress(asyncio.CancelledError):
            await consumer_task
        await nc.drain()
        await nc.close()
        await close_consortium_counter_deps(deps)


def main() -> None:
    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))
    asyncio.run(run())


if __name__ == "__main__":
    main()
