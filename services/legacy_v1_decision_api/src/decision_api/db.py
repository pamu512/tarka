import asyncio
import os
from collections.abc import AsyncGenerator
from pathlib import Path
from typing import Literal

from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from decision_api.config import settings
from tarka_core.database import (
    build_async_database_url,
    create_audit_async_engine,
    resolve_tarka_db_engine,
    sync_url_for_alembic,
)
from tarka_core.sqla_base import Base


def _app_root() -> Path:
    here = Path(__file__).resolve().parent
    for parent in (here, *here.parents):
        if (parent / "config" / "decision_alembic.ini").is_file():
            return parent
        if (parent / "alembic.ini").is_file():
            return parent
    return here.parent.parent.parent


_engine_kind: Literal["sqlite", "postgres"] = resolve_tarka_db_engine(
    database_url=settings.database_url
)
# Exposed for orchestration (e.g. Postgres-only audit ordering before Rust evaluation).
ENGINE_KIND: Literal["sqlite", "postgres"] = _engine_kind
_database_url = build_async_database_url(
    engine_kind=_engine_kind,
    database_url=settings.database_url,
    sqlite_database_path=_app_root() / "data" / "decision-api-dev.db",
)

engine = create_audit_async_engine(_database_url, engine_kind=_engine_kind)
SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async with SessionLocal() as session:
        yield session


def _sqlite_index_columns(connection: Connection, index_name: str) -> tuple[str, ...]:
    escaped = index_name.replace("'", "''")
    return tuple(
        str(row[2])
        for row in connection.exec_driver_sql(
            f"PRAGMA index_info('{escaped}')"
        ).fetchall()
    )


def _upgrade_sqlite_durable_idempotency(connection: Connection) -> None:
    """Upgrade an existing SQLite decision_audit table without rebuilding it."""
    columns = {
        str(row[1])
        for row in connection.exec_driver_sql(
            "PRAGMA table_info('decision_audit')"
        ).fetchall()
    }
    if not columns:
        return
    for column_name, column_type in (
        ("idempotency_key", "VARCHAR(512)"),
        ("request_fingerprint", "VARCHAR(64)"),
        ("idempotency_response", "JSON"),
    ):
        if column_name not in columns:
            connection.exec_driver_sql(
                f"ALTER TABLE decision_audit ADD COLUMN {column_name} {column_type}"
            )

    index_name = "uq_decision_audit_tenant_idempotency_key"
    indexes = {
        str(row[1]): bool(row[2])
        for row in connection.exec_driver_sql(
            "PRAGMA index_list('decision_audit')"
        ).fetchall()
    }
    if index_name in indexes:
        if not indexes[index_name] or _sqlite_index_columns(connection, index_name) != (
            "tenant_id",
            "idempotency_key",
        ):
            raise RuntimeError(
                f"SQLite index {index_name} has an incompatible definition"
            )
        return
    if not any(
        unique
        and _sqlite_index_columns(connection, existing_name)
        == ("tenant_id", "idempotency_key")
        for existing_name, unique in indexes.items()
    ):
        connection.exec_driver_sql(
            "CREATE UNIQUE INDEX uq_decision_audit_tenant_idempotency_key "
            "ON decision_audit (tenant_id, idempotency_key)"
        )


async def init_db() -> None:
    from decision_api import models as _models  # noqa: F401

    if os.environ.get("TARKA_SKIP_STARTUP_MIGRATIONS", "").strip().lower() in {
        "1",
        "true",
        "yes",
    }:
        return

    if _engine_kind == "sqlite":
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
            await conn.run_sync(_upgrade_sqlite_durable_idempotency)
        return

    os.environ["ALEMBIC_SYNC_DATABASE_URL"] = sync_url_for_alembic(_database_url)
    from alembic import command
    from alembic.config import Config

    cfg_path = _app_root() / "config" / "decision_alembic.ini"
    if not cfg_path.is_file():
        cfg_path = _app_root() / "alembic.ini"
    cfg = Config(str(cfg_path))
    await asyncio.to_thread(command.upgrade, cfg, "head")
