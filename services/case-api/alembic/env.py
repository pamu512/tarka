"""Alembic environment — sync migrations for PostgreSQL (SQLite tests use create_all)."""

from __future__ import annotations

import os
import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import create_engine, pool

if context.config.config_file_name:
    fileConfig(context.config.config_file_name)

_app_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_app_root / "src"))

from case_api import models as _models  # noqa: F401, E402
from case_api.db import Base  # noqa: E402

target_metadata = Base.metadata


def _to_sync_url(url: str) -> str:
    if not url:
        raise RuntimeError("DATABASE_URL or ALEMBIC_SYNC_DATABASE_URL must be set for migrations")
    if "+asyncpg" in url:
        return url.replace("postgresql+asyncpg", "postgresql+psycopg")
    if "sqlite+aiosqlite" in url:
        return url.replace("sqlite+aiosqlite://", "sqlite://")
    return url


def get_url() -> str:
    return _to_sync_url(os.environ.get("ALEMBIC_SYNC_DATABASE_URL") or os.environ.get("DATABASE_URL", ""))


def run_migrations_offline() -> None:
    url = get_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = create_engine(get_url(), poolclass=pool.NullPool)
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
