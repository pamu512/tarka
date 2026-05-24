"""Orchestrator database session helpers (transactional outbox, audit writes)."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

logger = logging.getLogger(__name__)

_READ_COMMITTED = "READ COMMITTED"


class TarkaDatabaseException(Exception):
    """Corporate wrapper for failed orchestrator database transactions."""

    def __init__(
        self,
        message: str,
        *,
        error_code: str = "database_transaction_failed",
        original: SQLAlchemyError | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.error_code = error_code
        self.original = original


def _resolve_bind(session_factory: async_sessionmaker[AsyncSession]) -> AsyncEngine:
    bind = session_factory.kw.get("bind")
    if bind is None:
        bind = getattr(session_factory, "bind", None)
    if bind is None:
        raise TarkaDatabaseException(
            "session factory is not bound to an async engine",
            error_code="database_factory_unbound",
        )
    if not isinstance(bind, AsyncEngine):
        raise TarkaDatabaseException(
            "session factory bind must be an AsyncEngine",
            error_code="database_factory_invalid_bind",
        )
    return bind


async def _apply_read_committed(conn: object) -> object:
    """Set READ COMMITTED on PostgreSQL; SQLite (tests) uses dialect default."""
    dialect_name = getattr(getattr(conn, "dialect", None), "name", "")
    if dialect_name == "sqlite":
        return conn
    execution_options = getattr(conn, "execution_options", None)
    if execution_options is None:
        raise TarkaDatabaseException(
            "connection does not support execution_options",
            error_code="database_connection_invalid",
        )
    return await execution_options(isolation_level=_READ_COMMITTED)


@asynccontextmanager
async def atomic_transaction(
    session_factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncSession]:
    """
    Yield an :class:`~sqlalchemy.ext.asyncio.AsyncSession` inside a single READ COMMITTED transaction.

    Isolation is applied on the connection **before** ``BEGIN``. The block commits on clean exit;
    on :class:`~sqlalchemy.exc.SQLAlchemyError` the transaction is rolled back, the traceback is
    logged, and :class:`TarkaDatabaseException` is raised.
    """
    engine = _resolve_bind(session_factory)
    try:
        async with engine.connect() as conn:
            conn = await _apply_read_committed(conn)
            session = session_factory.class_(
                bind=conn,
                expire_on_commit=session_factory.kw.get("expire_on_commit", False),
                join_transaction_mode="create_savepoint",
            )
            try:
                async with conn.begin():
                    try:
                        yield session
                    except SQLAlchemyError as exc:
                        await session.rollback()
                        logger.exception(
                            "atomic_transaction_sqlalchemy_error error_code=%s error_type=%s",
                            "database_transaction_failed",
                            type(exc).__name__,
                        )
                        raise TarkaDatabaseException(
                            "orchestrator database transaction failed",
                            original=exc,
                        ) from exc
            finally:
                await session.close()
    except SQLAlchemyError as exc:
        logger.exception(
            "atomic_transaction_sqlalchemy_error error_code=%s error_type=%s",
            "database_transaction_failed",
            type(exc).__name__,
        )
        raise TarkaDatabaseException(
            "orchestrator database transaction failed",
            original=exc,
        ) from exc
