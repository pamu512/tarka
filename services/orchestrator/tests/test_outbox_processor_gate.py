"""Gate: outbox processor claims and completes tasks; honors shutdown after batch."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

_SRC_ORCH = Path(__file__).resolve().parents[1] / "src"
_SRC_SHARED = Path(__file__).resolve().parents[2] / "shared"
_SRC_INGESTOR = Path(__file__).resolve().parents[2] / "ingestor" / "src"
for _p in (_SRC_ORCH, _SRC_SHARED, _SRC_INGESTOR):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


def test_process_outbox_batch_completes_graph_ingest_task(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _run() -> None:
        from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
        from sqlalchemy.pool import StaticPool

        import models.outbox  # noqa: F401
        import tarka_shared.audit_trail  # noqa: F401
        import tarka_shared.engine_rules  # noqa: F401
        import tarka_shared.fraud_rules  # noqa: F401

        from graph.client import NullGraphClient
        from models.outbox import (
            OUTBOX_EVENT_GRAPH_INGEST,
            OutboxDAO,
            OutboxORM,
            OutboxStatus,
        )
        from workers.outbox_processor import OutboxProcessorDeps, process_outbox_batch
        from tarka_shared.database.session import Base

        engine = create_async_engine(
            "sqlite+aiosqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        fac = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
        async with fac() as session:
            async with session.begin():
                await OutboxDAO.create_task(
                    session,
                    OUTBOX_EVENT_GRAPH_INGEST,
                    "graph_ingest:entity-1:1",
                    {
                        "audit_log_id": 1,
                        "edge_transaction_payload_envelope": {
                            "entity_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
                            "amount": 10.0,
                            "timestamp": "2026-05-09T12:00:00+00:00",
                            "metadata": {"user_id": "u1"},
                        },
                    },
                )

        execute_mock = AsyncMock()
        monkeypatch.setattr(
            "orchestrator.workers.handlers.graph_ingest.GraphIngestHandler.execute",
            execute_mock,
        )

        deps = OutboxProcessorDeps(
            session_factory=fac,
            graph_client=NullGraphClient(),
            redis_client=None,
        )
        stats = await process_outbox_batch(deps, batch_size=10)
        assert stats.claimed == 1
        assert stats.completed == 1
        assert stats.failed == 0
        execute_mock.assert_awaited_once()

        async with fac() as session:
            row = (await session.scalars(select(OutboxORM))).one()
        assert row.status == OutboxStatus.COMPLETED.value
        assert row.processed_at is not None
        await engine.dispose()

    asyncio.run(_run())


def test_process_outbox_batch_fails_unknown_event_type_routing_error() -> None:
    async def _run() -> None:
        from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
        from sqlalchemy.pool import StaticPool

        import models.outbox  # noqa: F401
        import tarka_shared.audit_trail  # noqa: F401
        import tarka_shared.engine_rules  # noqa: F401
        import tarka_shared.fraud_rules  # noqa: F401

        from graph.client import NullGraphClient
        from models.outbox import OutboxDAO, OutboxORM, OutboxStatus
        from workers.outbox_processor import OutboxProcessorDeps, process_outbox_batch
        from tarka_shared.database.session import Base

        engine = create_async_engine(
            "sqlite+aiosqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        fac = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
        async with fac() as session:
            async with session.begin():
                await OutboxDAO.create_task(
                    session,
                    "UNKNOWN_EVENT",
                    "unknown:entity-1:1",
                    {"entity_id": "entity-1"},
                )

        deps = OutboxProcessorDeps(
            session_factory=fac,
            graph_client=NullGraphClient(),
            redis_client=None,
        )
        stats = await process_outbox_batch(deps, batch_size=10)
        assert stats.claimed == 1
        assert stats.completed == 0
        assert stats.failed == 1

        async with fac() as session:
            row = (await session.scalars(select(OutboxORM))).one()
        assert row.status == OutboxStatus.FAILED.value
        assert "no handler registered" in (row.last_error or "")
        await engine.dispose()

    asyncio.run(_run())


def test_process_outbox_batch_skips_when_redis_lock_held(monkeypatch: pytest.MonkeyPatch) -> None:
    class _LockRedis:
        def __init__(self) -> None:
            self.locks: set[str] = set()
            self.deletes: list[str] = []

        async def set(
            self, key: str, value: object, *, nx: bool = False, ex: int | None = None
        ) -> bool | None:
            _ = value, ex
            if nx and key in self.locks:
                return None
            self.locks.add(key)
            return True

        async def delete(self, key: str) -> int:
            self.deletes.append(key)
            self.locks.discard(key)
            return 1

    async def _run() -> None:
        from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
        from sqlalchemy.pool import StaticPool

        import models.outbox  # noqa: F401
        import tarka_shared.audit_trail  # noqa: F401
        import tarka_shared.engine_rules  # noqa: F401
        import tarka_shared.fraud_rules  # noqa: F401

        from graph.client import NullGraphClient
        from models.outbox import (
            OUTBOX_EVENT_GRAPH_INGEST,
            OutboxDAO,
            OutboxORM,
            OutboxStatus,
        )
        from workers.outbox_processor import OutboxProcessorDeps, process_outbox_batch
        from tarka_shared.database.session import Base

        engine = create_async_engine(
            "sqlite+aiosqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        fac = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
        idempotency_key = "graph_ingest:entity-1:1"
        async with fac() as session:
            async with session.begin():
                await OutboxDAO.create_task(
                    session,
                    OUTBOX_EVENT_GRAPH_INGEST,
                    idempotency_key,
                    {
                        "audit_log_id": 1,
                        "edge_transaction_payload_envelope": {
                            "entity_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
                            "amount": 10.0,
                            "timestamp": "2026-05-09T12:00:00+00:00",
                            "metadata": {"user_id": "u1"},
                        },
                    },
                )

        execute_mock = AsyncMock()
        monkeypatch.setattr(
            "orchestrator.workers.handlers.graph_ingest.GraphIngestHandler.execute",
            execute_mock,
        )

        lock_redis = _LockRedis()
        lock_redis.locks.add(f"outbox_lock:{idempotency_key}")

        deps = OutboxProcessorDeps(
            session_factory=fac,
            graph_client=NullGraphClient(),
            redis_client=lock_redis,
        )
        stats = await process_outbox_batch(deps, batch_size=10)
        assert stats.claimed == 1
        assert stats.completed == 0
        assert stats.failed == 0
        execute_mock.assert_not_awaited()

        async with fac() as session:
            row = (await session.scalars(select(OutboxORM))).one()
        assert row.status == OutboxStatus.PENDING.value
        await engine.dispose()

    asyncio.run(_run())


def test_process_outbox_batch_releases_redis_lock_on_handler_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _LockRedis:
        def __init__(self) -> None:
            self.locks: set[str] = set()
            self.deletes: list[str] = []

        async def set(
            self, key: str, value: object, *, nx: bool = False, ex: int | None = None
        ) -> bool | None:
            _ = value, ex
            if nx and key in self.locks:
                return None
            self.locks.add(key)
            return True

        async def delete(self, key: str) -> int:
            self.deletes.append(key)
            self.locks.discard(key)
            return 1

    async def _run() -> None:
        from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
        from sqlalchemy.pool import StaticPool

        import models.outbox  # noqa: F401
        import tarka_shared.audit_trail  # noqa: F401
        import tarka_shared.engine_rules  # noqa: F401
        import tarka_shared.fraud_rules  # noqa: F401

        from graph.client import NullGraphClient
        from models.outbox import (
            OUTBOX_EVENT_GRAPH_INGEST,
            OutboxDAO,
            OutboxORM,
            OutboxStatus,
        )
        from workers.outbox_processor import OutboxProcessorDeps, process_outbox_batch
        from tarka_shared.database.session import Base

        engine = create_async_engine(
            "sqlite+aiosqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        fac = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
        idempotency_key = "graph_ingest:entity-2:1"
        async with fac() as session:
            async with session.begin():
                await OutboxDAO.create_task(
                    session,
                    OUTBOX_EVENT_GRAPH_INGEST,
                    idempotency_key,
                    {
                        "audit_log_id": 1,
                        "edge_transaction_payload_envelope": {
                            "entity_id": "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
                            "amount": 10.0,
                            "timestamp": "2026-05-09T12:00:00+00:00",
                            "metadata": {"user_id": "u2"},
                        },
                    },
                )

        execute_mock = AsyncMock(side_effect=RuntimeError("handler boom"))
        monkeypatch.setattr(
            "orchestrator.workers.handlers.graph_ingest.GraphIngestHandler.execute",
            execute_mock,
        )

        lock_redis = _LockRedis()
        deps = OutboxProcessorDeps(
            session_factory=fac,
            graph_client=NullGraphClient(),
            redis_client=lock_redis,
        )
        stats = await process_outbox_batch(deps, batch_size=10)
        assert stats.claimed == 1
        assert stats.completed == 0
        assert stats.failed == 1
        assert lock_redis.deletes == [f"outbox_lock:{idempotency_key}"]

        async with fac() as session:
            row = (await session.scalars(select(OutboxORM))).one()
        assert row.status == OutboxStatus.FAILED.value
        await engine.dispose()

    asyncio.run(_run())


def test_run_worker_graceful_shutdown_after_batch(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _run() -> None:
        import workers.outbox_processor as mod
        from graph.client import NullGraphClient
        from workers.outbox_processor import OutboxProcessorConfig, OutboxProcessorDeps

        config = OutboxProcessorConfig(
            audit_database_url="sqlite+aiosqlite:///:memory:",
            poll_interval_sec=60.0,
            batch_size=10,
            log_level="INFO",
        )

        close_mock = AsyncMock()
        build_mock = AsyncMock(
            return_value=(
                OutboxProcessorDeps(
                    session_factory=AsyncMock(),
                    graph_client=NullGraphClient(),
                    redis_client=None,
                ),
                AsyncMock(),
            ),
        )
        batch_mock = AsyncMock(return_value=mod.OutboxBatchStats(claimed=1, completed=1))

        monkeypatch.setattr(mod, "build_processor_deps", build_mock)
        monkeypatch.setattr(mod, "close_processor_deps", close_mock)
        monkeypatch.setattr(mod, "process_outbox_batch", batch_mock)

        stop_holder: dict[str, asyncio.Event | None] = {"stop": None}

        def _capture_stop(stop: asyncio.Event) -> None:
            stop_holder["stop"] = stop

        monkeypatch.setattr(mod, "install_signal_handlers", _capture_stop)

        task = asyncio.create_task(mod.run_worker(config))
        for _ in range(100):
            await asyncio.sleep(0.01)
            if batch_mock.await_count >= 1 and stop_holder["stop"] is not None:
                break
        assert batch_mock.await_count >= 1
        assert stop_holder["stop"] is not None
        stop_holder["stop"].set()
        await asyncio.wait_for(task, timeout=2.0)

        assert batch_mock.await_count == 1
        close_mock.assert_awaited_once()

    asyncio.run(_run())
