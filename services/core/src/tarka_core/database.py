"""Audit-plane async SQLAlchemy engine factory (PostgreSQL + SQLite)."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

from sqlalchemy.engine.url import make_url
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

EngineKind = Literal["sqlite", "postgres"]


def resolve_tarka_db_engine(*, database_url: str) -> EngineKind:
    """Resolve storage engine from ``TARKA_DB_ENGINE`` and ``DATABASE_URL``.

    Precedence:

    1. If the ``TARKA_DB_ENGINE`` environment variable is **set** (including empty),
       treat ``postgres`` / ``postgresql`` as PostgreSQL and anything else (including
       empty) as SQLite — this matches Tarka Micro's ``TARKA_DB_ENGINE=sqlite`` default
       when the key is present with no value.
    2. Otherwise infer from ``database_url``: ``sqlite`` if the URL names SQLite, else
       PostgreSQL for ``postgres`` / ``postgresql`` URLs.
    """
    if "TARKA_DB_ENGINE" in os.environ:
        raw = (os.environ.get("TARKA_DB_ENGINE") or "sqlite").strip().lower()
        if raw in ("postgres", "postgresql"):
            return "postgres"
        return "sqlite"

    url = (database_url or "").strip().lower()
    if "sqlite" in url:
        return "sqlite"
    if "postgres" in url or "postgresql" in url:
        return "postgres"
    return "sqlite"


def _ensure_postgresql_asyncpg(url: str) -> str:
    u = make_url(url)
    if u.drivername == "postgresql+asyncpg":
        return str(u)
    if u.drivername == "postgresql":
        return str(u.set(drivername="postgresql+asyncpg"))
    if u.drivername.startswith("postgresql+"):
        return str(u.set(drivername="postgresql+asyncpg"))
    return url


def _ensure_sqlite_aiosqlite(url: str) -> str:
    u = make_url(url)
    if u.drivername == "sqlite+aiosqlite":
        return str(u)
    if u.drivername == "sqlite":
        return str(u.set(drivername="sqlite+aiosqlite"))
    return url


def build_async_database_url(
    *,
    engine_kind: EngineKind,
    database_url: str,
    sqlite_database_path: Path,
) -> str:
    """Build the async SQLAlchemy URL for the configured engine."""
    if engine_kind == "postgres":
        return _ensure_postgresql_asyncpg(database_url)

    raw = (database_url or "").strip()
    if raw and "sqlite" in raw.lower():
        return _ensure_sqlite_aiosqlite(raw)
    sqlite_database_path.parent.mkdir(parents=True, exist_ok=True)
    return f"sqlite+aiosqlite:///{sqlite_database_path.resolve()}"


def sync_url_for_alembic(async_url: str) -> str:
    """Derive a synchronous migration URL from an async SQLAlchemy URL."""
    if "+asyncpg" in async_url:
        return async_url.replace("postgresql+asyncpg", "postgresql+psycopg")
    if "sqlite+aiosqlite" in async_url:
        return async_url.replace("sqlite+aiosqlite://", "sqlite://")
    return async_url


def _pool_size() -> int:
    return max(1, int(os.environ.get("TARKA_DB_POOL_SIZE", "5")))


def _max_overflow() -> int:
    return max(0, int(os.environ.get("TARKA_DB_MAX_OVERFLOW", "10")))


def create_audit_async_engine(url: str, *, engine_kind: EngineKind, echo: bool = False) -> AsyncEngine:
    """Create a production-ready async engine for the audit plane."""
    if engine_kind == "sqlite":
        return create_async_engine(
            url,
            echo=echo,
            connect_args={"check_same_thread": False},
            pool_pre_ping=True,
        )

    return create_async_engine(
        url,
        echo=echo,
        pool_pre_ping=True,
        pool_size=_pool_size(),
        max_overflow=_max_overflow(),
    )


def install_sqlite_migration_compilers() -> None:
    """Register JSONB → JSON and UUID → CHAR compilers for SQLite (Alembic)."""
    import importlib

    importlib.import_module("tarka_core.dialect_compat")
