"""
Durable JetStream pull consumer for ``shadow.investigate`` (orchestrator publishes on REVIEW).

Each message is evaluated through :meth:`~shadow_agent.agent.ShadowAgent.evaluate` under the
configured AI gateway, producing append-only ``audit_logs`` rows identical to ``POST /v1/analyze``.

Messages are acked only after evaluation and audit persistence succeed; retryable engine
failures trigger ``nak(delay=5)``.

Run (requires ``pip install tarka-orchestrator[worker]`` and shadow-agent on ``PYTHONPATH``)::

    NATS_URL=nats://127.0.0.1:4222 SHADOW_DATABASE_URL=postgresql+asyncpg://... \\
      python -m orchestrator.workers.nats_shadow_investigate
"""

from __future__ import annotations

import asyncio
import json
import logging
import signal
from typing import Any

from orchestrator.config import get_settings
from orchestrator.messaging.shadow_investigate_jetstream import (
    ensure_shadow_investigate_stream,
    shadow_investigate_durable_name,
    shadow_investigate_fetch_batch_size,
    shadow_investigate_stream_name,
)
from orchestrator.queues.shadow_dispatch import shadow_investigate_subject

logger = logging.getLogger(__name__)

_NAK_DELAY_SEC = 5


def is_retryable_engine_failure(exc: BaseException) -> bool:
    """True when the Shadow evaluate path should be redelivered after a short delay."""
    import httpx  # noqa: PLC0415
    from sqlalchemy.exc import DBAPIError, OperationalError  # noqa: PLC0415
    from tarka_shared.audit_errors import AuditPersistenceError  # noqa: PLC0415

    if isinstance(
        exc,
        (
            AuditPersistenceError,
            ConnectionError,
            TimeoutError,
            OSError,
            OperationalError,
            DBAPIError,
        ),
    ):
        return True
    if isinstance(exc, httpx.HTTPError):
        return True
    if isinstance(exc, httpx.TimeoutException):
        return True
    return False


def decode_shadow_investigate_payload(msg: Any) -> dict[str, Any]:
    raw = getattr(msg, "data", None)
    if not raw:
        return {}
    try:
        payload = json.loads(raw.decode())
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


async def process_shadow_investigate_message(runtime: Any, msg: Any) -> None:
    """
    Evaluate one JetStream message and ``ack`` / ``nak`` explicitly.

    ``ack`` only after ShadowAgent evaluation + audit commit; ``nak(delay=5)`` on retryable failures.
    """
    from shadow_agent.workers.shadow_investigate_handler import handle_shadow_investigate_payload  # noqa: PLC0415

    payload = decode_shadow_investigate_payload(msg)
    logger.info(
        "shadow_investigate_recv session_id=%s entity_id=%s",
        payload.get("session_id"),
        payload.get("entity_id"),
    )
    try:
        committed = await handle_shadow_investigate_payload(runtime, payload)
    except Exception as exc:
        if is_retryable_engine_failure(exc):
            logger.warning(
                "shadow_investigate_retryable_failure session_id=%s entity_id=%s exc_type=%s",
                payload.get("session_id"),
                payload.get("entity_id"),
                type(exc).__name__,
            )
            await msg.nak(delay=_NAK_DELAY_SEC)
            return
        logger.exception(
            "shadow_investigate_unrecoverable_failure session_id=%s entity_id=%s",
            payload.get("session_id"),
            payload.get("entity_id"),
        )
        await msg.ack()
        return

    if not committed:
        await msg.ack()
        return

    await msg.ack()


async def run_pull_consumer(
    *,
    runtime: Any,
    js: Any,
    subject: str,
    stop: asyncio.Event,
) -> None:
    """Explicit JetStream fetch loop using ``sub.fetch(batch_size=10)``."""
    import nats.errors  # noqa: PLC0415

    stream_name = shadow_investigate_stream_name()
    durable = shadow_investigate_durable_name()
    batch_size = shadow_investigate_fetch_batch_size()

    await ensure_shadow_investigate_stream(js, subject=subject)
    sub = await js.pull_subscribe(subject, durable=durable, stream=stream_name)
    logger.info(
        "nats_shadow_investigate_pull_subscribed stream=%s subject=%s durable=%s batch=%s",
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
            logger.exception("shadow_investigate_fetch_failed")
            await asyncio.sleep(1.0)
            continue

        for msg in msgs:
            if stop.is_set():
                break
            await process_shadow_investigate_message(runtime, msg)


async def run() -> None:
    settings = get_settings()
    nats_url = settings.require_nats_url(purpose="shadow.investigate JetStream worker")

    try:
        import nats  # noqa: PLC0415
    except ImportError as exc:
        raise RuntimeError(
            "nats-py is required (pip install tarka-orchestrator[worker])",
        ) from exc

    from shadow_agent.workers.runtime import (  # noqa: PLC0415
        bootstrap_shadow_investigate_runtime,
        shutdown_shadow_investigate_runtime,
    )

    runtime = await bootstrap_shadow_investigate_runtime()
    subject = shadow_investigate_subject()
    nc = await nats.connect(nats_url)
    js = nc.jetstream()
    if js is None:
        await nc.drain()
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
        run_pull_consumer(runtime=runtime, js=js, subject=subject, stop=stop),
    )
    logger.info(
        "nats_shadow_investigate_worker_started subject=%s gateway=%s",
        subject,
        type(runtime.gateway).__name__,
    )

    try:
        await stop.wait()
    finally:
        consumer_task.cancel()
        with asyncio.suppress(asyncio.CancelledError):
            await consumer_task
        await nc.drain()
        await nc.close()
        await shutdown_shadow_investigate_runtime(runtime)


def main() -> None:
    logging.basicConfig(level=get_settings().log_level)
    asyncio.run(run())


if __name__ == "__main__":
    main()
