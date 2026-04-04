import os
from collections.abc import AsyncGenerator
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from case_api.config import settings

engine = create_async_engine(settings.database_url, echo=False)
SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def _is_sqlite(url: str) -> bool:
    return "sqlite" in url.lower()


def _sync_url_for_alembic(url: str) -> str:
    if "+asyncpg" in url:
        return url.replace("postgresql+asyncpg", "postgresql+psycopg")
    if "sqlite+aiosqlite" in url:
        return url.replace("sqlite+aiosqlite://", "sqlite://")
    return url


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async with SessionLocal() as session:
        yield session


async def init_db() -> None:
    from case_api import models as _models  # noqa: F401

    if _is_sqlite(settings.database_url):
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        return

    os.environ["ALEMBIC_SYNC_DATABASE_URL"] = _sync_url_for_alembic(settings.database_url)
    from alembic import command
    from alembic.config import Config

    app_root = Path(__file__).resolve().parent.parent.parent
    cfg = Config(str(app_root / "alembic.ini"))
    command.upgrade(cfg, "head")
