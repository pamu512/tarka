import os
from collections.abc import AsyncGenerator
from pathlib import Path
from typing import Literal

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase

from decision_api.config import settings
from tarka_core.database import (
    build_async_database_url,
    create_audit_async_engine,
    resolve_tarka_db_engine,
    sync_url_for_alembic,
)


def _app_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent


_engine_kind: Literal["sqlite", "postgres"] = resolve_tarka_db_engine(
    database_url=settings.database_url
)
_database_url = build_async_database_url(
    engine_kind=_engine_kind,
    database_url=settings.database_url,
    sqlite_database_path=_app_root() / "data" / "decision-api-dev.db",
)

engine = create_audit_async_engine(_database_url, engine_kind=_engine_kind)
SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async with SessionLocal() as session:
        yield session


async def init_db() -> None:
    from decision_api import models as _models  # noqa: F401

    if _engine_kind == "sqlite":
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        return

    os.environ["ALEMBIC_SYNC_DATABASE_URL"] = sync_url_for_alembic(_database_url)
    from alembic import command
    from alembic.config import Config

    cfg = Config(str(_app_root() / "alembic.ini"))
    command.upgrade(cfg, "head")
