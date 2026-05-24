"""
Standalone async worker: drain ``tarka_outbox`` (``GRAPH_INGEST``, ``VELOCITY_UPDATE``, …).

Run::

    ORCHESTRATOR_AUDIT_DATABASE_URL=postgresql+asyncpg://user:pass@host/db \\
    ANUMANA_REDIS_URL=redis://127.0.0.1:6379 \\
    OUTBOX_POLL_INTERVAL_SECONDS=2 \\
      python -m orchestrator.workers.outbox_processor
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import signal
import sys
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

import orchestrator.models.outbox  # noqa: F401 — register ORM metadata
import tarka_shared.audit_trail  # noqa: F401
import tarka_shared.engine_rules  # noqa: F401
import tarka_shared.fraud_rules  # noqa: F401

from orchestrator.audit_case_worker import build_audit_engine, resolve_audit_database_url
from orchestrator.config import get_settings
from orchestrator.database import TarkaDatabaseException, atomic_transaction
from orchestrator.graph.client import NullGraphClient, graph_client_from_environment
from orchestrator.models.outbox import OutboxDAO, OutboxORM, OutboxStatus
from orchestrator.workers.handlers.base import BaseOutboxHandler, OutboxProcessorDeps
from orchestrator.workers.handlers.graph_ingest import GraphIngestHandler
from orchestrator.workers.handlers.label_propagator import LabelPropagatorHandler
from orchestrator.workers.handlers.shadow_retro_tag import ShadowRetroTagHandler
from orchestrator.workers.handlers.velocity_update import VelocityUpdateHandler
from tarka_shared.database.session import Base

logger = logging.getLogger(__name__)

OUTBOX_LOCK_KEY_PREFIX = "outbox_lock:"
OUTBOX_LOCK_TTL_SEC = 600


class OutboxRoutingError(Exception):
    """Raised when ``event_type`` has no registered handler (unrecoverable routing failure)."""


class OutboxLockNotAcquired(Exception):
    """Raised when another worker holds the Redis deduplication lock for this idempotency key."""


def _outbox_lock_key(idempotency_key: str) -> str:
    token = (idempotency_key or "").strip()
    if not token:
        raise ValueError("idempotency_key must be non-empty to build an outbox lock key")
    return f"{OUTBOX_LOCK_KEY_PREFIX}{token}"


async def _try_acquire_outbox_lock(redis_client: Any, idempotency_key: str) -> bool:
    """Atomic ``SET key 1 NX EX 600`` — returns True when this worker owns the lock."""
    key = _outbox_lock_key(idempotency_key)
    acquired = await redis_client.set(key, 1, nx=True, ex=OUTBOX_LOCK_TTL_SEC)
    return bool(acquired)


async def _release_outbox_lock(redis_client: Any, idempotency_key: str) -> None:
    """Drop the lock so a failed handler can be retried immediately."""
    key = _outbox_lock_key(idempotency_key)
    await redis_client.delete(key)


@dataclass(frozen=True, slots=True)
class OutboxProcessorConfig:
    audit_database_url: str
    poll_interval_sec: float
    batch_size: int
    log_level: str


@dataclass
class OutboxBatchStats:
    claimed: int = 0
    completed: int = 0
    failed: int = 0

    def as_log_dict(self) -> dict[str, int]:
        return {
            "claimed": self.claimed,
            "completed": self.completed,
            "failed": self.failed,
        }


def load_config() -> OutboxProcessorConfig:
    audit_url = resolve_audit_database_url()
    if not audit_url:
        raise RuntimeError(
            "ORCHESTRATOR_AUDIT_DATABASE_URL (or SHADOW_DATABASE_URL) is required for the outbox worker",
        )
    settings = get_settings()
    return OutboxProcessorConfig(
        audit_database_url=audit_url,
        poll_interval_sec=settings.outbox_poll_interval_seconds,
        batch_size=settings.outbox_batch_size,
        log_level=settings.log_level,
    )


def _resolve_redis_url() -> str | None:
    url = get_settings().resolved_anumana_redis_url
    return url or None


def _resolve_nats_url() -> str | None:
    url = get_settings().nats_url.strip()
    return url or None


async def _connect_nats_jetstream() -> tuple[Any | None, Any | None]:
    nats_url = _resolve_nats_url()
    if not nats_url:
        logger.warning(
            "outbox_processor_nats_unconfigured label_propagate_tasks_will_fail env=NATS_URL",
        )
        return None, None
    try:
        import nats  # noqa: PLC0415
    except ImportError as exc:
        raise RuntimeError(
            "NATS_URL is set but nats-py is not installed (pip install tarka-orchestrator[worker])",
        ) from exc

    from orchestrator.messaging.nats_jetstream import TarkaEventsJetStreamInitializer  # noqa: PLC0415

    nc = await nats.connect(nats_url)
    js = nc.jetstream()
    if js is None:
        await nc.drain()
        raise RuntimeError("NATS JetStream context is not available on the broker")
    await TarkaEventsJetStreamInitializer.from_environment().ensure_streams_on(js)
    logger.info("outbox_processor_nats_jetstream_ready url=%s", nats_url.split("@")[-1])
    return js, nc


async def build_processor_deps(config: OutboxProcessorConfig) -> tuple[OutboxProcessorDeps, AsyncEngine]:
    engine = build_audit_engine(config.audit_database_url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    redis_client: Any | None = None
    redis_url = _resolve_redis_url()
    if redis_url:
        import redis.asyncio as redis_mod  # noqa: PLC0415

        redis_client = redis_mod.from_url(redis_url, decode_responses=False)
    else:
        logger.warning(
            "outbox_processor_redis_unconfigured velocity_update_tasks_will_fail "
            "env=ANUMANA_REDIS_URL|ANUMANA_TELEMETRY_REDIS_URL",
        )

    graph_client = graph_client_from_environment()
    if isinstance(graph_client, NullGraphClient):
        logger.warning(
            "outbox_processor_graph_client_null graph_ingest_tasks_will_noop "
            "env=GRAPH_BACKEND|NEO4J_URI|GREMLIN_REMOTE_URL",
        )

    from orchestrator.analytics.cloud_provider import _try_connect_clickhouse  # noqa: PLC0415

    clickhouse_client = _try_connect_clickhouse()
    if clickhouse_client is None:
        logger.warning(
            "outbox_processor_clickhouse_unconfigured velocity_update_clickhouse_skipped "
            "env=CLICKHOUSE_HOST|CLICKHOUSE_URL",
        )

    nats_js, nats_nc = await _connect_nats_jetstream()

    return (
        OutboxProcessorDeps(
            session_factory=session_factory,
            graph_client=graph_client,
            redis_client=redis_client,
            clickhouse_client=clickhouse_client,
            nats_jetstream=nats_js,
            nats_connection=nats_nc,
        ),
        engine,
    )


async def close_processor_deps(deps: OutboxProcessorDeps, engine: AsyncEngine) -> None:
    gc = deps.graph_client
    close_fn = getattr(gc, "close", None)
    if close_fn is not None:
        try:
            await close_fn()
        except Exception:
            logger.exception("outbox_processor_graph_client_close_failed")
    if deps.redis_client is not None:
        try:
            await deps.redis_client.aclose()
        except Exception:
            logger.exception("outbox_processor_redis_close_failed")
    if deps.clickhouse_client is not None:
        try:
            close_fn = getattr(deps.clickhouse_client, "close", None)
            if callable(close_fn):
                close_fn()
        except Exception:
            logger.exception("outbox_processor_clickhouse_close_failed")
    if deps.nats_connection is not None:
        try:
            await deps.nats_connection.drain()
        except Exception:
            logger.exception("outbox_processor_nats_close_failed")
    await engine.dispose()


TASK_HANDLERS: dict[str, type[BaseOutboxHandler]] = {
    GraphIngestHandler.event_type: GraphIngestHandler,
    VelocityUpdateHandler.event_type: VelocityUpdateHandler,
    LabelPropagatorHandler.event_type: LabelPropagatorHandler,
    ShadowRetroTagHandler.event_type: ShadowRetroTagHandler,
}


def resolve_outbox_handler(event_type: str, deps: OutboxProcessorDeps) -> BaseOutboxHandler:
    token = (event_type or "").strip()
    handler_cls = TASK_HANDLERS.get(token)
    if handler_cls is None:
        raise OutboxRoutingError(f"no handler registered for event_type={token!r}")
    return handler_cls(deps)


async def release_task_claim(
    session_factory: async_sessionmaker[AsyncSession],
    task_id: UUID,
) -> None:
    """Return a claimed row to ``PENDING`` when execution is skipped (e.g. Redis lock held)."""
    async with atomic_transaction(session_factory) as session:
        stmt = (
            update(OutboxORM)
            .where(
                OutboxORM.id == task_id,
                OutboxORM.status == OutboxStatus.PROCESSING.value,
            )
            .values(status=OutboxStatus.PENDING.value)
        )
        await session.execute(stmt)


async def route_outbox_task(task: OutboxORM, *, deps: OutboxProcessorDeps) -> None:
    payload = task.payload if isinstance(task.payload, dict) else {}
    event_type = (task.event_type or "").strip()
    idempotency_key = (task.idempotency_key or "").strip()

    lock_acquired = False
    if deps.redis_client is not None and idempotency_key:
        lock_acquired = await _try_acquire_outbox_lock(deps.redis_client, idempotency_key)
        if not lock_acquired:
            raise OutboxLockNotAcquired(idempotency_key)

    try:
        handler = resolve_outbox_handler(event_type, deps)
    except OutboxRoutingError:
        logger.error(
            "outbox_processor_unrecoverable_routing_error task_id=%s event_type=%s idempotency_key=%s",
            task.id,
            event_type,
            task.idempotency_key,
        )
        if lock_acquired and deps.redis_client is not None and idempotency_key:
            await _release_outbox_lock(deps.redis_client, idempotency_key)
        raise

    try:
        await handler.execute(payload)
    except Exception:
        if lock_acquired and deps.redis_client is not None and idempotency_key:
            await _release_outbox_lock(deps.redis_client, idempotency_key)
        raise


async def claim_pending_batch(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    batch_size: int,
) -> list[OutboxORM]:
    """Claim up to ``batch_size`` rows (``PROCESSING``) inside one READ COMMITTED transaction."""
    async with atomic_transaction(session_factory) as session:
        pending = await OutboxDAO.fetch_pending_tasks(session, batch_size=batch_size)
        claimed: list[OutboxORM] = []
        for row in pending:
            claimed.append(await OutboxDAO.mark_processing(session, row.id))
        return claimed


async def finalize_task_success(
    session_factory: async_sessionmaker[AsyncSession],
    task_id: UUID,
) -> None:
    async with atomic_transaction(session_factory) as session:
        await OutboxDAO.mark_completed(session, task_id)


async def finalize_task_failure(
    session_factory: async_sessionmaker[AsyncSession],
    task_id: UUID,
    error_msg: str,
) -> None:
    async with atomic_transaction(session_factory) as session:
        await OutboxDAO.mark_failed(session, task_id, error_msg)


async def process_outbox_batch(deps: OutboxProcessorDeps, *, batch_size: int) -> OutboxBatchStats:
    stats = OutboxBatchStats()
    try:
        tasks = await claim_pending_batch(deps.session_factory, batch_size=batch_size)
    except TarkaDatabaseException:
        logger.exception("outbox_processor_claim_batch_failed")
        raise

    stats.claimed = len(tasks)
    if not tasks:
        return stats

    logger.info("outbox_processor_batch_claimed count=%s", stats.claimed)

    for task in tasks:
        try:
            await route_outbox_task(task, deps=deps)
        except OutboxLockNotAcquired:
            logger.info(
                "outbox_processor_lock_skip task_id=%s event_type=%s idempotency_key=%s",
                task.id,
                task.event_type,
                task.idempotency_key,
            )
            try:
                await release_task_claim(deps.session_factory, task.id)
            except Exception:
                logger.exception(
                    "outbox_processor_release_claim_error task_id=%s event_type=%s",
                    task.id,
                    task.event_type,
                )
            continue
        except OutboxRoutingError as exc:
            try:
                await finalize_task_failure(deps.session_factory, task.id, str(exc))
            except Exception:
                logger.exception(
                    "outbox_processor_mark_failed_error task_id=%s event_type=%s",
                    task.id,
                    task.event_type,
                )
            else:
                stats.failed += 1
            continue
        except Exception as exc:
            logger.exception(
                "outbox_processor_task_execution_failed task_id=%s event_type=%s idempotency_key=%s",
                task.id,
                task.event_type,
                task.idempotency_key,
            )
            try:
                await finalize_task_failure(deps.session_factory, task.id, str(exc))
            except Exception:
                logger.exception(
                    "outbox_processor_mark_failed_error task_id=%s event_type=%s",
                    task.id,
                    task.event_type,
                )
            else:
                stats.failed += 1
            continue

        try:
            await finalize_task_success(deps.session_factory, task.id)
        except Exception:
            logger.exception(
                "outbox_processor_mark_completed_error task_id=%s event_type=%s",
                task.id,
                task.event_type,
            )
            stats.failed += 1
        else:
            stats.completed += 1
            logger.info(
                "outbox_processor_task_completed task_id=%s event_type=%s idempotency_key=%s",
                task.id,
                task.event_type,
                task.idempotency_key,
            )

    return stats


def install_signal_handlers(stop: asyncio.Event) -> None:
    def _request_stop(signum: int) -> None:
        logger.info(
            "outbox_processor_shutdown_signal_received signal=%s",
            signal.Signals(signum).name,
        )
        stop.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _request_stop, sig)
        except NotImplementedError:
            signal.signal(sig, lambda _signum, _frame, sig_num=sig: _request_stop(sig_num))


async def run_worker(config: OutboxProcessorConfig) -> None:
    deps, engine = await build_processor_deps(config)
    stop = asyncio.Event()
    install_signal_handlers(stop)

    logger.info(
        "outbox_processor_started poll_interval_sec=%s batch_size=%s",
        config.poll_interval_sec,
        config.batch_size,
    )

    try:
        while True:
            if stop.is_set():
                logger.info("outbox_processor_exiting_before_poll shutdown_requested=true")
                break

            try:
                stats = await process_outbox_batch(deps, batch_size=config.batch_size)
            except TarkaDatabaseException:
                stats = OutboxBatchStats()
            except Exception:
                logger.exception("outbox_processor_batch_unhandled_error")
                stats = OutboxBatchStats()

            if stats.claimed:
                logger.info("outbox_processor_batch_finished %s", stats.as_log_dict())

            if stop.is_set():
                logger.info("outbox_processor_exiting_after_batch shutdown_requested=true")
                break

            try:
                await asyncio.wait_for(stop.wait(), timeout=config.poll_interval_sec)
                logger.info("outbox_processor_shutdown_during_sleep")
                break
            except TimeoutError:
                continue
    finally:
        await close_processor_deps(deps, engine)
        logger.info("outbox_processor_stopped")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Poll tarka_outbox and execute side-effect tasks.")
    parser.parse_args(argv)

    config = load_config()
    logging.basicConfig(
        level=getattr(logging, config.log_level, logging.INFO),
        format="%(levelname)s %(name)s %(message)s",
        stream=sys.stderr,
    )

    try:
        asyncio.run(run_worker(config))
    except KeyboardInterrupt:
        logger.info("outbox_processor_keyboard_interrupt")


if __name__ == "__main__":
    main()
