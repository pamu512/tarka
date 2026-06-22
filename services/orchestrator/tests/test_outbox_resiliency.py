"""Integration tests: transactional outbox atomicity and worker retry recovery."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any
from unittest.mock import patch
from uuid import UUID

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import StaticPool

_SRC_ORCH = Path(__file__).resolve().parents[1]
_SRC_INGESTOR = Path(__file__).resolve().parents[2] / "ingestor" / "src"
_SRC_SHARED = Path(__file__).resolve().parents[2] / "shared"
for _p in (_SRC_ORCH, _SRC_INGESTOR, _SRC_SHARED):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

FLAKY_ENTITY_ID = "55555555-5555-5555-5555-555555555555"


@pytest.fixture
async def ephemeral_audit_db() -> async_sessionmaker[AsyncSession]:
    """In-memory SQLite with orchestrator audit + outbox schema."""
    import models.cases  # noqa: F401
    import models.decision  # noqa: F401
    import models.outbox  # noqa: F401
    import tarka_shared.audit_trail  # noqa: F401
    import tarka_shared.engine_rules  # noqa: F401
    import tarka_shared.fraud_rules  # noqa: F401

    from tarka_shared.audit_trail import AuditLog
    from tarka_shared.database.session import Base

    engine: AsyncEngine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    fac = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    fac._test_engine = engine  # type: ignore[attr-defined]
    fac._test_audit_log = AuditLog  # type: ignore[attr-defined]
    try:
        yield fac
    finally:
        await engine.dispose()


def _graph_ingest_payload(*, entity_id: str, audit_log_id: int) -> dict[str, Any]:
    return {
        "schema": "tarka.graph_ingest.v1",
        "transaction_id": entity_id,
        "entity_id": entity_id,
        "audit_log_id": audit_log_id,
        "resolved_rules": [],
        "blocking_rule_id": None,
        "edge_transaction_payload_envelope": {
            "entity_id": entity_id,
            "amount": 10.0,
            "timestamp": "2026-05-09T12:00:00+00:00",
            "metadata": {"user_id": "u-resiliency"},
        },
    }


@pytest.mark.asyncio
async def test_outbox_insert_failure_rolls_back_audit_and_decision_rows(
    ephemeral_audit_db: async_sessionmaker[AsyncSession],
) -> None:
    """When outbox insertion fails, Lekh + audit rows must not survive the atomic transaction."""
    from audit_case_worker import persist_orchestrator_audit_log
    from database import TarkaDatabaseException, atomic_transaction
    from enforcement.log_decision import persist_lekh_decision
    from models.decision import DecisionORM
    from models.outbox import (
        OUTBOX_EVENT_GRAPH_INGEST,
        OUTBOX_EVENT_VELOCITY_UPDATE,
        OutboxDAO,
        OutboxORM,
    )

    AuditLog = ephemeral_audit_db._test_audit_log  # type: ignore[attr-defined]
    fac = ephemeral_audit_db
    entity_id = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    rule_data: dict[str, Any] = {
        "actions": ["ALLOW"],
        "evaluation_trace": [],
        "blocking_rule_id": None,
        "transaction_id": entity_id,
    }

    original_create_task = OutboxDAO.create_task
    create_calls = 0

    async def _create_task_fail_on_second(
        session: AsyncSession,
        event_type: str,
        idempotency_key: str,
        payload: dict[str, Any],
    ) -> Any:
        nonlocal create_calls
        create_calls += 1
        if create_calls >= 2:
            raise IntegrityError(
                "simulated outbox insert failure",
                params=None,
                orig=Exception("duplicate idempotency"),
            )
        return await original_create_task(session, event_type, idempotency_key, payload)

    with patch.object(OutboxDAO, "create_task", _create_task_fail_on_second):
        with pytest.raises(TarkaDatabaseException):
            async with atomic_transaction(fac) as session:
                await persist_lekh_decision(session, entity_id=entity_id, rule_data=rule_data)
                audit_log_id = await persist_orchestrator_audit_log(
                    session,
                    entity_id=entity_id,
                    metadata={"user_id": "u1"},
                    actions=["ALLOW"],
                    rule_data=rule_data,
                    shadow_data=None,
                    shadow_matches=[],
                    transaction_envelope={"entity_id": entity_id, "amount": 10.0},
                )
                await OutboxDAO.create_task(
                    session,
                    OUTBOX_EVENT_GRAPH_INGEST,
                    f"graph_ingest:{entity_id}:{audit_log_id}",
                    _graph_ingest_payload(entity_id=entity_id, audit_log_id=audit_log_id),
                )
                await OutboxDAO.create_task(
                    session,
                    OUTBOX_EVENT_VELOCITY_UPDATE,
                    f"velocity_update:{entity_id}:{audit_log_id}",
                    {
                        "schema": "tarka.velocity_update.v1",
                        "entity_id": entity_id,
                        "amount_cents": 1000,
                        "transaction_timestamp_utc": "2026-05-09T12:00:00+00:00",
                    },
                )

    async with fac() as session:
        audit_count = await session.scalar(select(func.count()).select_from(AuditLog))
        decision_count = await session.scalar(select(func.count()).select_from(DecisionORM))
        outbox_count = await session.scalar(select(func.count()).select_from(OutboxORM))

    assert audit_count == 0
    assert decision_count == 0
    assert outbox_count == 0
    assert create_calls == 2


@pytest.mark.asyncio
async def test_worker_recovers_transient_handler_failure_while_other_tasks_complete(
    ephemeral_audit_db: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One flaky GRAPH_INGEST task retries after FAILED; the other nine complete in the first batch."""
    from graph.client import NullGraphClient
    from models.outbox import (
        OUTBOX_EVENT_GRAPH_INGEST,
        OutboxDAO,
        OutboxORM,
        OutboxStatus,
    )
    from workers.handlers.graph_ingest import GraphIngestHandler
    from workers.outbox_processor import OutboxProcessorDeps, process_outbox_batch

    fac = ephemeral_audit_db
    flaky_attempts: dict[str, int] = {}

    async def _flaky_execute(self: GraphIngestHandler, payload: dict[str, Any]) -> None:
        entity_id = str(payload.get("entity_id") or "")
        if entity_id == FLAKY_ENTITY_ID:
            flaky_attempts[entity_id] = flaky_attempts.get(entity_id, 0) + 1
            if flaky_attempts[entity_id] == 1:
                raise ConnectionError("transient graph backend unavailable")

    monkeypatch.setattr(
        "orchestrator.workers.handlers.graph_ingest.GraphIngestHandler.execute",
        _flaky_execute,
    )

    async with fac() as session:
        async with session.begin():
            for i in range(10):
                entity_id = FLAKY_ENTITY_ID if i == 5 else f"10000000-0000-0000-0000-{i:012x}"
                audit_log_id = i + 1
                await OutboxDAO.create_task(
                    session,
                    OUTBOX_EVENT_GRAPH_INGEST,
                    f"graph_ingest:{entity_id}:{audit_log_id}",
                    _graph_ingest_payload(entity_id=entity_id, audit_log_id=audit_log_id),
                )

    deps = OutboxProcessorDeps(
        session_factory=fac,
        graph_client=NullGraphClient(),
        redis_client=None,
        clickhouse_client=None,
    )

    first_pass = await process_outbox_batch(deps, batch_size=20)
    assert first_pass.claimed == 10
    assert first_pass.completed == 9
    assert first_pass.failed == 1
    assert flaky_attempts.get(FLAKY_ENTITY_ID) == 1

    async with fac() as session:
        rows_after_first = (await session.scalars(select(OutboxORM))).all()
        by_status = {
            r.status: sum(1 for x in rows_after_first if x.status == r.status)
            for r in rows_after_first
        }
        assert by_status.get(OutboxStatus.COMPLETED.value) == 9
        assert by_status.get(OutboxStatus.FAILED.value) == 1
        flaky_row = next(r for r in rows_after_first if FLAKY_ENTITY_ID in r.idempotency_key)
        assert flaky_row.retry_count == 1
        assert flaky_row.last_error is not None

    second_pass = await process_outbox_batch(deps, batch_size=20)
    assert second_pass.claimed == 1
    assert second_pass.completed == 1
    assert second_pass.failed == 0
    assert flaky_attempts.get(FLAKY_ENTITY_ID) == 2

    async with fac() as session:
        final_rows = (await session.scalars(select(OutboxORM).order_by(OutboxORM.created_at))).all()

    assert len(final_rows) == 10
    assert all(row.status == OutboxStatus.COMPLETED.value for row in final_rows)
    assert all(row.processed_at is not None for row in final_rows)

    recovered = next(r for r in final_rows if FLAKY_ENTITY_ID in r.idempotency_key)
    assert recovered.retry_count == 1
    assert recovered.last_error is not None


@pytest.mark.asyncio
async def test_worker_second_batch_claims_only_retryable_failed_tasks(
    ephemeral_audit_db: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """FAILED rows with retries remaining re-enter the claim set; COMPLETED rows are not reclaimed."""
    from graph.client import NullGraphClient
    from models.outbox import (
        OUTBOX_EVENT_GRAPH_INGEST,
        OutboxDAO,
        OutboxORM,
        OutboxStatus,
    )
    from workers.handlers.graph_ingest import GraphIngestHandler
    from workers.outbox_processor import OutboxProcessorDeps, process_outbox_batch

    fac = ephemeral_audit_db
    seen_task_ids: list[UUID] = []

    async def _track_execute(self: GraphIngestHandler, payload: dict[str, Any]) -> None:
        entity_id = str(payload.get("entity_id") or "")
        if entity_id == FLAKY_ENTITY_ID:
            raise TimeoutError("transient timeout")

    monkeypatch.setattr(
        "orchestrator.workers.handlers.graph_ingest.GraphIngestHandler.execute",
        _track_execute,
    )

    entity_ids = [f"20000000-0000-0000-0000-{i:012x}" for i in range(9)] + [FLAKY_ENTITY_ID]
    async with fac() as session:
        async with session.begin():
            for i, entity_id in enumerate(entity_ids):
                await OutboxDAO.create_task(
                    session,
                    OUTBOX_EVENT_GRAPH_INGEST,
                    f"graph_ingest:{entity_id}:{i + 1}",
                    _graph_ingest_payload(entity_id=entity_id, audit_log_id=i + 1),
                )

    deps = OutboxProcessorDeps(
        session_factory=fac,
        graph_client=NullGraphClient(),
        redis_client=None,
        clickhouse_client=None,
    )

    await process_outbox_batch(deps, batch_size=20)

    async with fac() as session:
        pending = await OutboxDAO.fetch_pending_tasks(session, batch_size=20)
        seen_task_ids.extend(row.id for row in pending)
        completed = (
            await session.scalars(
                select(OutboxORM).where(OutboxORM.status == OutboxStatus.COMPLETED.value),
            )
        ).all()

    assert len(seen_task_ids) == 1
    assert len(completed) == 9

    async def _noop_execute(self: GraphIngestHandler, payload: dict[str, Any]) -> None:
        return None

    monkeypatch.setattr(
        "orchestrator.workers.handlers.graph_ingest.GraphIngestHandler.execute",
        _noop_execute,
    )

    await process_outbox_batch(deps, batch_size=20)

    async with fac() as session:
        all_rows = (await session.scalars(select(OutboxORM))).all()

    assert len(all_rows) == 10
    assert all(row.status == OutboxStatus.COMPLETED.value for row in all_rows)
