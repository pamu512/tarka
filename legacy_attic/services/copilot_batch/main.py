"""
Standalone asyncio worker: every 60 seconds, aggregates spend per ``entity_id`` from
``audit_logs`` (same Postgres as ``core_v2`` via ``DATABASE_URL``) and emits whale alerts.

Not an HTTP service. Requires index ``ix_audit_logs_created_at`` on ``(created_at)`` for
windowed scans (see deploy init SQL).
"""

from __future__ import annotations

import asyncio
import logging
import os
import random
import signal
import sys
import time
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

import structlog
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, OperationalError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# Same relation as ``services/core_v2/db.py`` ``AuditLog``: JSON ``raw_payload`` holds API payload.
AGGREGATE_SQL = text("""
SELECT
    entity_id::text AS entity_id,
    SUM((raw_payload->>'amount')::double precision) AS total_amount
FROM audit_logs
WHERE created_at >= :window_start
GROUP BY entity_id
HAVING SUM((raw_payload->>'amount')::double precision) > :threshold
""")

LOOP_SLEEP_SECONDS = int(os.getenv("LOOP_SLEEP_SECONDS", "60"))
WHALE_THRESHOLD = float(os.getenv("WHALE_THRESHOLD", "50000.0"))
WINDOW_MINUTES = int(os.getenv("WINDOW_MINUTES", "60"))
QUERY_TIMEOUT_SEC = float(os.getenv("QUERY_TIMEOUT_SEC", "120.0"))
QUERY_SLOW_WARNING_MS = float(os.getenv("QUERY_SLOW_WARNING_MS", "500.0"))
MAX_QUERY_RETRIES = int(os.getenv("MAX_QUERY_RETRIES", "5"))
QUERY_RETRY_BASE_SEC = float(os.getenv("QUERY_RETRY_BASE_SEC", "0.5"))


def _configure_structlog() -> Any:
    structlog.configure(
        processors=[
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True, key="timestamp"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(file=sys.stdout),
        cache_logger_on_first_use=True,
    )
    return structlog.get_logger(__name__)


def _normalize_database_url(url: str) -> str:
    """Match ``core_v2``: async SQLAlchemy URL with ``asyncpg`` driver."""
    if url.startswith(("postgresql+asyncpg://", "postgres+asyncpg://")):
        return url
    if url.startswith("postgresql://"):
        return "postgresql+asyncpg://" + url.removeprefix("postgresql://")
    if url.startswith("postgres://"):
        return "postgresql+asyncpg://" + url.removeprefix("postgres://")
    return url


def _build_engine_and_session() -> tuple[Any, Any]:
    # Same env var as ``services/core_v2`` — shared Postgres for ``audit_logs``.
    raw = os.getenv(
        "DATABASE_URL",
        "postgresql+asyncpg://postgres:postgres@localhost:5432/tarka",
    ).strip()
    database_url = _normalize_database_url(raw)
    eng = create_async_engine(
        database_url,
        pool_size=int(os.getenv("COPILOT_DB_POOL_SIZE", "5")),
        max_overflow=int(os.getenv("COPILOT_DB_MAX_OVERFLOW", "0")),
        pool_pre_ping=True,
    )
    factory = async_sessionmaker(eng, class_=AsyncSession, expire_on_commit=False)
    return eng, factory


engine, async_session = _build_engine_and_session()


async def run_analysis_cycle(log: Any) -> None:
    """
    Sum ``raw_payload->>'amount'`` per ``entity_id`` for rows with ``created_at`` in the
    last ``WINDOW_MINUTES`` minutes; alert when sum exceeds ``WHALE_THRESHOLD``.

    Retries transient connectivity/query failures; logs slow queries (>500ms default).
    """
    window_start = datetime.now(UTC) - timedelta(minutes=WINDOW_MINUTES)
    params = {
        "window_start": window_start,
        "threshold": WHALE_THRESHOLD,
    }

    rows: Sequence[Any] | None = None
    elapsed_ms: float | None = None
    last_error: BaseException | None = None

    for attempt in range(1, MAX_QUERY_RETRIES + 1):
        async with async_session() as session:
            t0 = time.perf_counter()
            try:
                result = await asyncio.wait_for(
                    session.execute(AGGREGATE_SQL, params),
                    timeout=QUERY_TIMEOUT_SEC,
                )
                elapsed_ms = (time.perf_counter() - t0) * 1000.0
                rows = tuple(result.all())
                last_error = None

                if elapsed_ms > QUERY_SLOW_WARNING_MS:
                    log.warning(
                        "batch_analysis_query_slow",
                        elapsed_ms=round(elapsed_ms, 3),
                        warning_threshold_ms=QUERY_SLOW_WARNING_MS,
                        window_minutes=WINDOW_MINUTES,
                    )
                break

            except TimeoutError as exc:
                elapsed_ms = (time.perf_counter() - t0) * 1000.0
                last_error = exc
                log.error(
                    "batch_analysis_query_timeout",
                    attempt=attempt,
                    max_attempts=MAX_QUERY_RETRIES,
                    timeout_sec=QUERY_TIMEOUT_SEC,
                    elapsed_ms=round(elapsed_ms, 3),
                    exc_info=exc,
                )
                try:
                    await session.rollback()
                except DBAPIError as rb_exc:
                    log.warning("batch_analysis_rollback_failed", exc_info=rb_exc)

            except OperationalError as exc:
                elapsed_ms = (time.perf_counter() - t0) * 1000.0
                last_error = exc
                log.error(
                    "batch_analysis_operational_error",
                    attempt=attempt,
                    max_attempts=MAX_QUERY_RETRIES,
                    elapsed_ms=round(elapsed_ms, 3),
                    exc_info=exc,
                )
                try:
                    await session.rollback()
                except DBAPIError as rb_exc:
                    log.warning("batch_analysis_rollback_failed", exc_info=rb_exc)
                if attempt < MAX_QUERY_RETRIES:
                    delay = QUERY_RETRY_BASE_SEC * (2 ** (attempt - 1))
                    delay += random.uniform(0, delay * 0.2)
                    await asyncio.sleep(delay)

            except DBAPIError as exc:
                last_error = exc
                log.error(
                    "batch_analysis_dbapi_error",
                    attempt=attempt,
                    error=str(exc),
                    exc_info=True,
                )
                try:
                    await session.rollback()
                except DBAPIError as rb_exc:
                    log.warning("batch_analysis_rollback_failed", exc_info=rb_exc)
                break

            except Exception as exc:
                last_error = exc
                log.error(
                    "batch_analysis_failed",
                    attempt=attempt,
                    error=str(exc),
                    exc_info=True,
                )
                try:
                    await session.rollback()
                except DBAPIError as rb_exc:
                    log.warning("batch_analysis_rollback_failed", exc_info=rb_exc)
                break

    if last_error is not None:
        return
    if rows is None:
        log.error("batch_analysis_failed", reason="no_result_after_retries")
        return

    if not rows:
        log.info(
            "batch_analysis_complete",
            status="no_whales_detected",
            window_minutes=WINDOW_MINUTES,
            query_elapsed_ms=round(elapsed_ms, 3) if elapsed_ms is not None else None,
        )
        return

    for row in rows:
        entity_id, total = row[0], row[1]
        log.error(
            "LOW_FREQUENCY_WHALE_DETECTED",
            entity_id=entity_id,
            total_amount=float(total) if total is not None else None,
            window_minutes=WINDOW_MINUTES,
            threshold=WHALE_THRESHOLD,
        )

    log.info(
        "batch_analysis_complete",
        status="whales_detected",
        count=len(rows),
        window_minutes=WINDOW_MINUTES,
        query_elapsed_ms=round(elapsed_ms, 3) if elapsed_ms is not None else None,
    )


async def worker_main() -> None:
    log = _configure_structlog()
    log.info(
        "copilot_batch_worker_started",
        database_url_configured=bool(os.environ.get("DATABASE_URL", "").strip()),
        loop_sleep_seconds=LOOP_SLEEP_SECONDS,
        window_minutes=WINDOW_MINUTES,
        whale_threshold=WHALE_THRESHOLD,
    )

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)

    try:
        while not stop.is_set():
            await run_analysis_cycle(log)
            try:
                await asyncio.wait_for(stop.wait(), timeout=float(LOOP_SLEEP_SECONDS))
            except TimeoutError:
                continue
    finally:
        log.info("copilot_batch_worker_shutting_down")
        await engine.dispose()


def main() -> None:
    try:
        asyncio.run(worker_main())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
