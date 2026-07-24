"""FastAPI dependencies for durable infrastructure (Postgres asyncpg pool, ClickHouse client)."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import TypeVar

import anyio
import asyncpg
from clickhouse_connect.driver.client import Client
from fastapi import FastAPI, HTTPException, Request

from analytics.engine import BaseAnalyticsEngine

from decision_api.config import settings
from tarka_core.cache import KeyValueCache
from tarka_core.messaging import MessageBroker

log = logging.getLogger("decision-api")

T = TypeVar("T")


def _asyncpg_dsn_from_database_url() -> str | None:
    """Return a DSN suitable for asyncpg, or None when SQLite / unsupported URL."""
    u = settings.database_url
    if "sqlite" in u.lower():
        return None
    if u.startswith("postgresql+asyncpg://"):
        return "postgresql://" + u.removeprefix("postgresql+asyncpg://")
    if u.startswith("postgres://"):
        return "postgresql://" + u.removeprefix("postgres://")
    if u.startswith("postgresql://"):
        return u
    return None


async def run_clickhouse_sync(client: Client, fn: Callable[[], T]) -> T:
    """Run a synchronous clickhouse-connect call off the event loop."""
    return await anyio.to_thread.run_sync(fn)


async def run_analytics_sync(fn: Callable[[], T]) -> T:
    """Run a synchronous analytics engine call off the event loop."""
    return await anyio.to_thread.run_sync(fn)


async def open_analytics_infra(application: FastAPI) -> None:
    """Create asyncpg pool (Postgres only) and optional analytics engine (ClickHouse or DuckDB)."""
    application.state.pg_pool = None
    application.state.clickhouse_client = None
    application.state.analytics_engine = None

    dsn = _asyncpg_dsn_from_database_url()
    if dsn:
        application.state.pg_pool = await asyncpg.create_pool(
            dsn,
            min_size=1,
            max_size=16,
            command_timeout=120.0,
        )
        log.info("asyncpg pool initialized for decision-api metadata paths")

    from analytics.engine import ClickHouseEngine, get_analytics_engine

    application.state.analytics_engine = get_analytics_engine(
        clickhouse_host=settings.clickhouse_host,
        clickhouse_port=settings.clickhouse_port,
        clickhouse_user=settings.clickhouse_user,
        clickhouse_password=settings.clickhouse_password or "",
        clickhouse_database=settings.clickhouse_database,
        clickhouse_statement_timeout_ms=settings.clickhouse_statement_timeout_ms,
    )

    eng = application.state.analytics_engine
    if isinstance(eng, ClickHouseEngine):
        client = eng.client
        try:
            with anyio.fail_after(10.0):
                await run_clickhouse_sync(client, lambda: client.query("SELECT 1"))
        except Exception as e:
            log.warning(
                "ClickHouse startup health check failed (routes will fail closed): %s",
                e,
            )
            try:
                await run_clickhouse_sync(client, client.close)
            except Exception as close_exc:
                log.warning(
                    "ClickHouse client close after failed health check: %s", close_exc
                )
            application.state.analytics_engine = None
            application.state.clickhouse_client = None
            return

        application.state.clickhouse_client = client
        log.info("ClickHouse client initialized and passed startup health check")
    elif eng is not None:
        log.info("Analytics engine online (%s)", eng.backend)


async def close_analytics_infra(application: FastAPI) -> None:
    pool = getattr(application.state, "pg_pool", None)
    if pool is not None:
        await pool.close()
        application.state.pg_pool = None
    ch = getattr(application.state, "clickhouse_client", None)
    if ch is not None:
        await run_clickhouse_sync(ch, ch.close)
        application.state.clickhouse_client = None
    eng = getattr(application.state, "analytics_engine", None)
    if eng is not None and hasattr(eng, "close"):
        try:
            eng.close()
        except Exception as e:
            log.warning("Analytics engine shutdown: %s", e)
        application.state.analytics_engine = None


def get_pg_pool(request: Request) -> asyncpg.Pool:
    pool = getattr(request.app.state, "pg_pool", None)
    if pool is None:
        raise HTTPException(
            status_code=503,
            detail={
                "reason_code": "METADATA_POOL_UNAVAILABLE",
                "message": "PostgreSQL asyncpg pool is not available for this deployment profile.",
            },
        )
    return pool


def get_clickhouse(request: Request) -> Client:
    """Legacy dependency: returns the ClickHouse client when the analytics engine is ClickHouse."""
    client = getattr(request.app.state, "clickhouse_client", None)
    if client is not None:
        return client
    from analytics.engine import ClickHouseEngine

    eng = getattr(request.app.state, "analytics_engine", None)
    if isinstance(eng, ClickHouseEngine):
        return eng.client
    if not (settings.clickhouse_host or "").strip():
        raise HTTPException(
            status_code=503,
            detail={
                "reason_code": "ANALYTICS_ENGINE_OFFLINE",
                "message": "ClickHouse host is not configured.",
            },
        )
    raise HTTPException(
        status_code=503,
        detail={
            "reason_code": "ANALYTICS_ENGINE_OFFLINE",
            "message": "ClickHouse client is unavailable (misconfiguration or startup health check failed).",
        },
    )


def require_analytics_engine(request: Request) -> BaseAnalyticsEngine:
    eng = getattr(request.app.state, "analytics_engine", None)
    if eng is None:
        raise HTTPException(
            status_code=503,
            detail={
                "reason_code": "ANALYTICS_ENGINE_OFFLINE",
                "message": "Analytics engine is not available for this deployment profile.",
            },
        )
    return eng


def get_kv_cache(request: Request) -> KeyValueCache:
    cache = getattr(request.app.state, "kv_cache", None)
    if cache is None:
        raise HTTPException(
            status_code=503,
            detail={
                "reason_code": "KV_CACHE_UNAVAILABLE",
                "message": "Application key-value cache is not initialized.",
            },
        )
    return cache


def get_message_broker(request: Request) -> MessageBroker:
    broker = getattr(request.app.state, "message_broker", None)
    if broker is None:
        raise HTTPException(
            status_code=503,
            detail={
                "reason_code": "MESSAGE_BROKER_UNAVAILABLE",
                "message": "Application message broker is not initialized.",
            },
        )
    return broker
