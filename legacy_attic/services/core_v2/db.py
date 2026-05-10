from __future__ import annotations

import asyncio
import os
import uuid
from collections.abc import AsyncGenerator
from datetime import datetime
from typing import Any

import redis.asyncio as redis
import structlog
from fastapi import HTTPException
from redis.exceptions import RedisError
from sqlalchemy import JSON, DateTime, String, Uuid, event, func
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, Mapper, mapped_column

logger = structlog.get_logger(__name__)


class Base(DeclarativeBase):
    """SQLAlchemy 2.0 declarative base for Core v2 ORM models."""


class AuditLogMutationForbiddenError(RuntimeError):
    """Append-only `AuditLog` rows cannot be updated or deleted via the ORM."""


class AuditLog(Base):
    """
    Append-only audit trail linking each assessed transaction to its decision outcome.

    Mutations are blocked at the ORM layer (`before_update` / `before_delete`). Bulk Core
    SQL or DDL can still bypass these hooks and must be forbidden operationally.
    """

    __tablename__ = "audit_logs"
    __table_args__ = {"comment": "Append-only audit records for Core v2 decisions."}

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    entity_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        nullable=False,
        index=True,
    )
    raw_payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    decision: Mapped[str] = mapped_column(String(512), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


@event.listens_for(AuditLog, "before_update", propagate=True)
def _reject_audit_log_update(mapper: Mapper, connection, target: AuditLog) -> None:
    raise AuditLogMutationForbiddenError(
        "AuditLog rows are append-only and cannot be updated.",
    )


@event.listens_for(AuditLog, "before_delete", propagate=True)
def _reject_audit_log_delete(mapper: Mapper, connection, target: AuditLog) -> None:
    raise AuditLogMutationForbiddenError(
        "AuditLog rows are append-only and cannot be deleted.",
    )


def _database_url() -> str:
    url = os.environ.get("DATABASE_URL", "").strip()
    if not url:
        msg = "DATABASE_URL must be set to a SQLAlchemy async URL (e.g. postgresql+asyncpg://...)"
        raise RuntimeError(msg)
    return url


engine = create_async_engine(
    _database_url(),
    pool_size=20,
    max_overflow=10,
    pool_pre_ping=True,
)

AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)

# --- Async Redis (optional speed layer; API must stay up if Redis is unavailable) ---

_redis_pool: redis.ConnectionPool | None = None
_redis_client: redis.Redis | None = None


async def _dispose_redis_handles(
    client: redis.Redis | None,
    pool: redis.ConnectionPool | None,
) -> None:
    """Best-effort teardown; never raises."""
    if client is not None:
        try:
            await client.aclose()
        except (RedisError, OSError) as exc:
            logger.warning("redis_client_aclose_failed", exc_info=exc)
    if pool is not None:
        try:
            await pool.disconnect(inuse_connections=True)
        except (RedisError, OSError) as exc:
            logger.warning("redis_pool_disconnect_failed", exc_info=exc)


async def init_redis_pool() -> None:
    """
    Build a shared ``redis.asyncio`` pool and verify connectivity with ``PING``.

    On any failure, logs a warning, leaves ``redis_client_for_publish()`` as ``None``,
    and **never raises** so application startup is not aborted.
    """
    global _redis_pool, _redis_client

    await shutdown_redis_pool()

    redis_url = os.environ.get("REDIS_URL", "redis://127.0.0.1:6379/0").strip()
    pool: redis.ConnectionPool | None = None
    client: redis.Redis | None = None

    try:
        max_conn = int(os.environ.get("REDIS_MAX_CONNECTIONS", "32"))
        connect_timeout = float(os.environ.get("REDIS_SOCKET_CONNECT_TIMEOUT", "2.0"))
        socket_timeout = float(os.environ.get("REDIS_SOCKET_TIMEOUT", "2.0"))
        pool = redis.ConnectionPool.from_url(
            redis_url,
            max_connections=max_conn,
            decode_responses=True,
            socket_connect_timeout=connect_timeout,
            socket_timeout=socket_timeout,
        )
        client = redis.Redis(connection_pool=pool)
        await asyncio.wait_for(client.ping(), timeout=connect_timeout)
    except asyncio.TimeoutError as exc:
        logger.warning(
            "redis_pool_init_degraded",
            reason="ping_timeout",
            redis_url_host=redis_url.split("@")[-1],
            exc_info=exc,
        )
        await _dispose_redis_handles(client, pool)
        return
    except (RedisError, OSError, ValueError) as exc:
        logger.warning(
            "redis_pool_init_degraded",
            reason="connection_or_configuration_error",
            redis_url_host=redis_url.split("@")[-1],
            exc_info=exc,
        )
        await _dispose_redis_handles(client, pool)
        return

    _redis_pool = pool
    _redis_client = client
    logger.info("redis_pool_ready", max_connections=max_conn)


async def shutdown_redis_pool() -> None:
    """Release pool and client handles. Safe to call multiple times; never raises."""
    global _redis_pool, _redis_client

    client = _redis_client
    pool = _redis_pool
    _redis_client = None
    _redis_pool = None
    await _dispose_redis_handles(client, pool)


def redis_client_for_publish() -> redis.Redis | None:
    """
    Shared async Redis client for fire-and-forget publishers (no per-call health probe).

    Callers must tolerate ``None`` and must not propagate Redis errors into HTTP responses.
    """
    return _redis_client


async def get_redis() -> AsyncGenerator[redis.Redis | None, None]:
    """
    FastAPI dependency: yields the shared async Redis client after a bounded ``PING``,
    or ``None`` if Redis was never initialized, initialization failed, or the probe fails.

    **Never raises** — hybrid sidecar integration must not take down request handling.
    """
    client = _redis_client
    if client is None:
        logger.warning(
            "get_redis_unavailable",
            reason="no_client_pool_uninitialized_or_degraded",
        )
        yield None
        return

    ping_timeout = float(os.environ.get("REDIS_DEPENDENCY_PING_TIMEOUT", "0.5"))
    try:
        await asyncio.wait_for(client.ping(), timeout=ping_timeout)
    except asyncio.TimeoutError as exc:
        logger.warning(
            "get_redis_degraded",
            reason="ping_timeout",
            exc_info=exc,
        )
        yield None
        return
    except (RedisError, OSError) as exc:
        logger.warning(
            "get_redis_degraded",
            reason="ping_failed",
            exc_info=exc,
        )
        yield None
        return

    yield client


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except OperationalError as exc:
            await session.rollback()
            logger.error("database_operational_error", exc_info=exc)
            raise HTTPException(
                status_code=503,
                detail="Database temporarily unavailable",
            ) from exc
        except Exception:
            await session.rollback()
            raise
