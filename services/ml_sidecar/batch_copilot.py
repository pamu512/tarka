"""
Batch copilot worker: scans recent ``audit_logs`` for high-aggregate spend (whale pattern).

Uses SQLAlchemy 2 async engine + sessions. Interval and thresholds come from environment.
"""

from __future__ import annotations

import asyncio
import logging
import os
import signal
import sys
from datetime import datetime, timedelta, timezone
from typing import Any

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

WHALE_SQL = text("""
SELECT
    entity_id::text AS entity_id,
    SUM((raw_payload->>'amount')::double precision) AS total_amount
FROM audit_logs
WHERE created_at >= :window_start
GROUP BY entity_id
HAVING SUM((raw_payload->>'amount')::double precision) > :threshold
""")


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
    """Ensure async driver prefix for ``create_async_engine``."""
    if url.startswith("postgresql+asyncpg://") or url.startswith("postgres+asyncpg://"):
        return url
    if url.startswith("postgresql://"):
        return "postgresql+asyncpg://" + url.removeprefix("postgresql://")
    if url.startswith("postgres://"):
        return "postgresql+asyncpg://" + url.removeprefix("postgres://")
    return url


DATABASE_URL = _normalize_database_url(
    os.getenv(
        "DATABASE_URL",
        "postgresql+asyncpg://postgres:postgres@localhost:5432/tarka",
    ),
)
BATCH_INTERVAL_SECONDS = int(os.getenv("BATCH_INTERVAL_SECONDS", "60"))
WHALE_THRESHOLD = float(os.getenv("WHALE_THRESHOLD", "50000.0"))

engine = create_async_engine(
    DATABASE_URL,
    pool_size=5,
    max_overflow=0,
    pool_pre_ping=True,
)

async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def analyze_trends(log: Any) -> None:
    """
    Scan the last 60 minutes of audit logs for entities whose summed ``amount``
    (from ``raw_payload`` JSON) exceeds ``WHALE_THRESHOLD``.
    """
    window_start = datetime.now(timezone.utc) - timedelta(minutes=60)

    async with async_session() as session:
        try:
            result = await session.execute(
                WHALE_SQL,
                {"window_start": window_start, "threshold": WHALE_THRESHOLD},
            )
            whale_rows = result.all()
        except Exception as exc:
            log.error("batch_analysis_failed", error=str(exc), exc_info=True)
            return

    if not whale_rows:
        log.info("batch_analysis_complete", status="no_whales_detected")
        return

    for row in whale_rows:
        entity_id, total = row[0], row[1]
        log.error(
            "LOW_FREQUENCY_WHALE_DETECTED",
            entity_id=entity_id,
            total_amount=float(total) if total is not None else None,
            window="60m",
            threshold=WHALE_THRESHOLD,
        )

    log.info(
        "batch_analysis_complete",
        status="whales_detected",
        count=len(whale_rows),
    )


async def main_loop() -> None:
    log = _configure_structlog()
    log.info("batch_copilot_started", interval_seconds=BATCH_INTERVAL_SECONDS)

    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop_event.set)

    try:
        while not stop_event.is_set():
            await analyze_trends(log)
            try:
                await asyncio.wait_for(
                    stop_event.wait(),
                    timeout=float(BATCH_INTERVAL_SECONDS),
                )
            except asyncio.TimeoutError:
                continue
    finally:
        log.info("batch_copilot_shutting_down")
        await engine.dispose()


def main() -> None:
    try:
        asyncio.run(main_loop())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
