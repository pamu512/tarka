"""Gate: atomic_transaction commits on success and wraps SQLAlchemy failures."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

_SRC_ORCH = Path(__file__).resolve().parents[1] / "src"
_SRC_SHARED = Path(__file__).resolve().parents[2] / "shared"
for _p in (_SRC_ORCH, _SRC_SHARED):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


def test_atomic_transaction_commits_on_success() -> None:
    async def _run() -> None:
        from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
        from sqlalchemy.pool import StaticPool

        from orchestrator.database import atomic_transaction

        engine = create_async_engine(
            "sqlite+aiosqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        fac = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
        async with engine.begin() as conn:
            await conn.execute(
                text("CREATE TABLE t_probe (id INTEGER PRIMARY KEY, v TEXT NOT NULL)")
            )

        async with atomic_transaction(fac) as session:
            await session.execute(text("INSERT INTO t_probe (id, v) VALUES (1, 'ok')"))

        async with fac() as session:
            row = (await session.execute(text("SELECT v FROM t_probe WHERE id = 1"))).scalar_one()
        assert row == "ok"
        await engine.dispose()

    asyncio.run(_run())


def test_atomic_transaction_wraps_sqlalchemy_error() -> None:
    async def _run() -> None:
        from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
        from sqlalchemy.pool import StaticPool

        from orchestrator.database import TarkaDatabaseException, atomic_transaction

        engine = create_async_engine(
            "sqlite+aiosqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        fac = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
        async with engine.begin() as conn:
            await conn.execute(
                text("CREATE TABLE t_probe2 (id INTEGER PRIMARY KEY, v TEXT NOT NULL)")
            )

        class _BrokenSession(AsyncSession):
            async def execute(self, *args: object, **kwargs: object) -> object:
                raise SQLAlchemyError("simulated driver failure")

        broken_fac = async_sessionmaker(
            bind=engine,
            expire_on_commit=False,
            class_=_BrokenSession,
        )

        with pytest.raises(TarkaDatabaseException) as raised:
            async with atomic_transaction(broken_fac) as session:
                await session.execute(text("INSERT INTO t_probe2 (id, v) VALUES (1, 'x')"))

        assert raised.value.error_code == "database_transaction_failed"
        assert isinstance(raised.value.original, SQLAlchemyError)
        await engine.dispose()

    asyncio.run(_run())
