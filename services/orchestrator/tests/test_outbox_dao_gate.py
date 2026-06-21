"""Gate: OutboxDAO CRUD against in-memory SQLite."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

_SRC_ORCH = Path(__file__).resolve().parents[1] / "src"
_SRC_SHARED = Path(__file__).resolve().parents[2] / "shared"
for _p in (_SRC_ORCH, _SRC_SHARED):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


def test_outbox_dao_lifecycle() -> None:
    async def _run() -> None:
        from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
        from sqlalchemy.pool import StaticPool

        from models.outbox import (
            OutboxDAO,
            OutboxORM,
            OutboxStatus,
            OutboxTaskNotFoundError,
        )
        from tarka_shared.database.session import Base

        engine = create_async_engine(
            "sqlite+aiosqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all, tables=[OutboxORM.__table__])

        fac = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

        async with fac() as session:
            async with session.begin():
                row = await OutboxDAO.create_task(
                    session,
                    "GRAPH_INGEST",
                    "idem-1",
                    {"case_id": "c-1"},
                )
                assert row.status == OutboxStatus.PENDING.value
                assert row.retry_count == 0

        async with fac() as session:
            async with session.begin():
                pending = await OutboxDAO.fetch_pending_tasks(session)
                assert len(pending) == 1
                task_id = pending[0].id

        async with fac() as session:
            async with session.begin():
                done = await OutboxDAO.mark_completed(session, task_id)
                assert done.status == OutboxStatus.COMPLETED.value
                assert done.processed_at is not None

        async with fac() as session:
            async with session.begin():
                assert await OutboxDAO.fetch_pending_tasks(session) == []

        async with fac() as session:
            async with session.begin():
                failed_row = await OutboxDAO.create_task(
                    session,
                    "SHADOW_TAG",
                    "idem-2",
                    {"tag": "x"},
                )
                failed_id = failed_row.id

        async with fac() as session:
            async with session.begin():
                failed = await OutboxDAO.mark_failed(session, failed_id, "boom")
                assert failed.status == OutboxStatus.FAILED.value
                assert failed.retry_count == 1
                assert failed.last_error == "boom"

        async with fac() as session:
            async with session.begin():
                retryable = await OutboxDAO.fetch_pending_tasks(session)
                assert len(retryable) == 1
                assert retryable[0].id == failed_id

        async with fac() as session:
            async with session.begin():
                from uuid import uuid4

                with pytest.raises(OutboxTaskNotFoundError):
                    await OutboxDAO.mark_failed(session, uuid4(), "no such task")

        await engine.dispose()

    asyncio.run(_run())
