"""Alembic environment for ``tarka_shared`` metadata (evidence locker / Shadow ``cases``)."""

from __future__ import annotations

import os
import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import create_engine, pool
from sqlalchemy.engine.url import make_url

if context.config.config_file_name is not None:
    fileConfig(context.config.config_file_name)

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import tarka_shared.audit_trail  # noqa: F401, E402 — register mappers
from tarka_shared.database.session import Base  # noqa: E402

target_metadata = Base.metadata

_ALEMBIC_VERSION_TABLE = "alembic_version_evidence_locker"


def _to_sync_url(url: str) -> str:
    if not url:
        raise RuntimeError(
            "Set ALEMBIC_SYNC_DATABASE_URL (or DATABASE_URL / SHADOW_DATABASE_URL) for migrations"
        )
    if "+asyncpg" in url:
        return url.replace("postgresql+asyncpg", "postgresql+psycopg")
    if "postgresql+psycopg" in url:
        return url
    if "sqlite+aiosqlite" in url:
        return url.replace("sqlite+aiosqlite://", "sqlite://")
    return url


def get_url() -> str:
    return _to_sync_url(
        (
            os.environ.get("ALEMBIC_SYNC_DATABASE_URL")
            or os.environ.get("DATABASE_URL")
            or os.environ.get("SHADOW_DATABASE_URL")
            or ""
        ).strip()
    )


def _is_sqlite_migration_url(url: str) -> bool:
    try:
        return make_url(url).get_backend_name() == "sqlite"
    except Exception:
        return "sqlite" in (url or "").lower()


def run_migrations_offline() -> None:
    url = get_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        version_table=_ALEMBIC_VERSION_TABLE,
        render_as_batch=_is_sqlite_migration_url(url),
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    url = get_url()
    connectable = create_engine(url, poolclass=pool.NullPool)
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            version_table=_ALEMBIC_VERSION_TABLE,
            render_as_batch=_is_sqlite_migration_url(url),
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
