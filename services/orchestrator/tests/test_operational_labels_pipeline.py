"""Integration: operational signal ingress → normalized_labels → label propagator."""

from __future__ import annotations

import asyncio
import json
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool
from starlette.testclient import TestClient

_SRC_ORCH = Path(__file__).resolve().parents[1]
_SRC_INGESTOR = Path(__file__).resolve().parents[2] / "ingestor" / "src"
_SRC_SHARED = Path(__file__).resolve().parents[2] / "shared"
_SRC_SERVICES = Path(__file__).resolve().parents[2]
for _p in (_SRC_ORCH, _SRC_INGESTOR, _SRC_SHARED, _SRC_SERVICES):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

_AUTH_HEADERS = {"X-Auth-Token": "gate-operational-pipeline-token"}
_MOCK_SHADOW_STRUCTURAL_TAGS = [
    "vector:chargeback",
    "matched_rule:velocity_ip",
    "ground_truth:fraud",
]


def _chargeback_body(*, entity_id: str, idempotency_key: str = "cb:pipeline:4853") -> dict:
    return {
        "idempotency_key": idempotency_key,
        "target_entity_id": entity_id,
        "signal_type": "CHARGEBACK_RECEIVED",
        "metadata": {
            "amount_cents": 1250,
            "currency": "USD",
            "chargeback_reason_code": "4853",
            "card_network": "VISA",
        },
    }


def _redis_mock(*, lock_acquired: bool = True) -> AsyncMock:
    redis = AsyncMock()
    redis.set = AsyncMock(return_value=lock_acquired)
    redis.delete = AsyncMock(return_value=1)
    redis.ping = AsyncMock(return_value=True)
    return redis


def _build_operational_signals_app(*, session_factory, redis_client):
    from deps.v1_api_guard import V1_PROTECTED_ROUTE_DEPENDENCIES
    from routes.operational_signals import router as operational_signals_router

    app = FastAPI()
    app.state.audit_session_factory = session_factory
    app.state.anumana_redis = redis_client
    app.state.v1_rate_limiter = None
    app.include_router(
        operational_signals_router,
        prefix="/v1",
        dependencies=V1_PROTECTED_ROUTE_DEPENDENCIES,
    )
    return app


async def _seed_entity_context(
    fac: async_sessionmaker[AsyncSession],
    *,
    entity_id: str,
) -> tuple[str, int]:
    import models.cases  # noqa: F401
    import models.decision  # noqa: F401
    import models.label_dlq  # noqa: F401
    import models.normalized_labels  # noqa: F401
    import models.operational_signals  # noqa: F401
    import models.outbox  # noqa: F401
    import tarka_shared.audit_trail  # noqa: F401
    import tarka_shared.engine_rules  # noqa: F401
    import tarka_shared.fraud_rules  # noqa: F401

    from audit_case_worker import ORCHESTRATOR_AUDIT_SOURCE
    from models.cases import CaseORM, CaseStatus
    from models.decision import DecisionORM
    from tarka_shared.audit_trail import AuditLog, Case
    from tarka_shared.case_status import DEFAULT_CASE_STATUS
    from tarka_shared.data.tenant_constants import DEFAULT_TENANT_ID

    shadow_case_id = str(uuid.uuid4())
    case_uuid = str(uuid.uuid4())

    async with fac() as session:
        async with session.begin():
            session.add(
                Case(
                    id=shadow_case_id,
                    tenant_id=DEFAULT_TENANT_ID,
                    name="shadow-anchor",
                    dataset_path=None,
                    is_active=False,
                    status=DEFAULT_CASE_STATUS,
                ),
            )
            ingest_log = AuditLog(
                case_id=shadow_case_id,
                action_taken=json.dumps(
                    {
                        "source": ORCHESTRATOR_AUDIT_SOURCE,
                        "entity_id": entity_id,
                        "transaction_envelope": {
                            "entity_id": entity_id,
                            "amount": 12.50,
                            "timestamp": "2026-05-09T12:00:00+00:00",
                            "metadata": {
                                "user_id": "u-operational-pipeline",
                                "chargeback_reason_code": "4853",
                            },
                        },
                    },
                    separators=(",", ":"),
                ),
                agent_notes=None,
                code_executed=None,
                timestamp=datetime(2026, 8, 1, 10, 0, 0, tzinfo=UTC),
            )
            session.add(ingest_log)
            await session.flush()
            session.add(
                CaseORM(
                    case_id=case_uuid,
                    transaction_id=int(ingest_log.id),
                    user_link_key="u-operational-pipeline",
                    entity_id=entity_id,
                    status=CaseStatus.OPEN.value,
                    priority=1,
                ),
            )
            session.add(
                DecisionORM(
                    entity_id=entity_id,
                    final_decision="FLAG",
                    actions_json=["FLAG"],
                    execution_trace_json=[{"rule_id": "velocity_ip", "matched": True}],
                    blocking_rule_id=None,
                    raw_rule_engine_json={
                        "transaction_id": entity_id,
                        "evaluation_trace": [{"rule_id": "velocity_ip", "matched": True}],
                    },
                ),
            )
            audit_log_id = int(ingest_log.id)

    return case_uuid, audit_log_id


async def _create_db_factory():
    import models.cases  # noqa: F401
    import models.decision  # noqa: F401
    import models.label_dlq  # noqa: F401
    import models.normalized_labels  # noqa: F401
    import models.operational_signals  # noqa: F401
    import models.outbox  # noqa: F401
    import tarka_shared.audit_trail  # noqa: F401
    import tarka_shared.engine_rules  # noqa: F401
    import tarka_shared.fraud_rules  # noqa
    from tarka_shared.database.session import Base

    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    fac = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    return engine, fac


async def _run_label_propagator_for_pending_outbox(
    fac: async_sessionmaker[AsyncSession],
    *,
    mock_shadow_tags: list[str],
) -> None:
    from graph.client import NullGraphClient
    from label_propagation import validate_label_propagate_payload
    from models.outbox import OUTBOX_EVENT_LABEL_PROPAGATE, OutboxORM
    from workers.handlers.base import OutboxProcessorDeps
    from workers.handlers.label_propagator import LabelPropagatorHandler

    async with fac() as session:
        outbox_row = await session.scalar(
            select(OutboxORM).where(OutboxORM.event_type == OUTBOX_EVENT_LABEL_PROPAGATE).limit(1),
        )
        assert outbox_row is not None
        payload = validate_label_propagate_payload(dict(outbox_row.payload))

    async def _run_inference(fn):
        return await fn()

    runtime = SimpleNamespace(
        llm_client=SimpleNamespace(),
        gateway=SimpleNamespace(
            run_shadow_investigate_inference=AsyncMock(side_effect=_run_inference),
        ),
    )
    jetstream = SimpleNamespace(publish=AsyncMock())

    with patch(
        "shadow_agent.retroactive_label.evaluate_retroactive_label",
        new=AsyncMock(return_value=list(mock_shadow_tags)),
    ) as retro_mock:
        handler = LabelPropagatorHandler(
            OutboxProcessorDeps(
                session_factory=fac,
                graph_client=NullGraphClient(),
                redis_client=None,
                shadow_runtime=runtime,
                nats_jetstream=jetstream,
            ),
        )
        await handler.execute(payload)

    retro_mock.assert_awaited_once()
    feedback = retro_mock.await_args.kwargs.get("feedback_context") or retro_mock.await_args.args[1]
    assert isinstance(feedback, dict)
    assert feedback.get("ground_truth_class") == "FRAUD"
    assert isinstance(feedback.get("operational_metadata"), dict)
    assert feedback["operational_metadata"].get("chargeback_reason_code") == "4853"
    jetstream.publish.assert_awaited_once()


def test_operational_chargeback_pipeline_persists_signal_and_shadow_retro_outbox(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ORCHESTRATOR_V1_RATE_LIMIT_RPM", "0")

    async def _run() -> None:
        from models.operational_signals import OperationalSignalORM
        from models.outbox import OUTBOX_EVENT_SHADOW_RETRO_TAG, OutboxORM

        entity_id = str(uuid.uuid4())
        engine, fac = await _create_db_factory()
        await _seed_entity_context(fac, entity_id=entity_id)

        app = _build_operational_signals_app(session_factory=fac, redis_client=_redis_mock())
        body = _chargeback_body(entity_id=entity_id)

        with TestClient(app) as client:
            response = client.post("/v1/operational-signals", json=body, headers=_AUTH_HEADERS)
            assert response.status_code == 202, response.text
            event_id = uuid.UUID(response.json()["event_id"])

        async with fac() as session:
            signal_count = await session.scalar(
                select(func.count()).select_from(OperationalSignalORM)
            )
            assert int(signal_count or 0) == 1

            signal_row = await session.get(OperationalSignalORM, event_id)
            assert signal_row is not None
            assert signal_row.idempotency_key == body["idempotency_key"]
            assert signal_row.target_entity_id == entity_id
            assert signal_row.signal_type == "CHARGEBACK_RECEIVED"
            assert signal_row.metadata_json["chargeback_reason_code"] == "4853"

            outbox_row = await session.scalar(
                select(OutboxORM).where(OutboxORM.event_type == OUTBOX_EVENT_SHADOW_RETRO_TAG),
            )
            assert outbox_row is not None
            assert outbox_row.idempotency_key == f"shadow_tag_ops:{body['idempotency_key']}"
            assert outbox_row.payload["entity_id"] == entity_id
            assert outbox_row.payload["metadata"]["chargeback_reason_code"] == "4853"

        await engine.dispose()

    asyncio.run(_run())


def test_operational_chargeback_idempotent_replay_does_not_duplicate_outbox(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ORCHESTRATOR_V1_RATE_LIMIT_RPM", "0")

    async def _run() -> None:
        from models.operational_signals import OperationalSignalORM
        from models.outbox import OUTBOX_EVENT_SHADOW_RETRO_TAG, OutboxORM

        entity_id = str(uuid.uuid4())
        engine, fac = await _create_db_factory()
        await _seed_entity_context(fac, entity_id=entity_id)

        redis = _redis_mock()
        redis.set = AsyncMock(side_effect=[True, None])
        app = _build_operational_signals_app(session_factory=fac, redis_client=redis)
        body = _chargeback_body(entity_id=entity_id, idempotency_key="cb:pipeline:replay")

        with TestClient(app) as client:
            first = client.post("/v1/operational-signals", json=body, headers=_AUTH_HEADERS)
            second = client.post("/v1/operational-signals", json=body, headers=_AUTH_HEADERS)
            assert first.status_code == 202, first.text
            assert second.status_code == 202, second.text
            assert first.json()["event_id"] == second.json()["event_id"]

        async with fac() as session:
            assert (
                int(
                    await session.scalar(select(func.count()).select_from(OperationalSignalORM))
                    or 0
                )
                == 1
            )
            assert (
                int(
                    await session.scalar(
                        select(func.count())
                        .select_from(OutboxORM)
                        .where(
                            OutboxORM.event_type == OUTBOX_EVENT_SHADOW_RETRO_TAG,
                        ),
                    ),
                )
                or 0
            ) == 1

        await engine.dispose()

    asyncio.run(_run())


def test_operational_pipeline_via_outbox_processor_batch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ORCHESTRATOR_V1_RATE_LIMIT_RPM", "0")

    async def _run() -> None:
        from graph.client import NullGraphClient
        from models.normalized_labels import NormalizedLabelORM
        from workers.handlers.base import OutboxProcessorDeps
        from workers.outbox_processor import process_outbox_batch

        entity_id = str(uuid.uuid4())
        engine, fac = await _create_db_factory()
        await _seed_entity_context(fac, entity_id=entity_id)

        app = _build_operational_signals_app(session_factory=fac, redis_client=_redis_mock())
        with TestClient(app) as client:
            response = client.post(
                "/v1/operational-signals",
                json=_chargeback_body(entity_id=entity_id, idempotency_key="cb:pipeline:batch"),
                headers=_AUTH_HEADERS,
            )
            assert response.status_code == 202, response.text
            event_id = uuid.UUID(response.json()["event_id"])

        runtime = SimpleNamespace(
            evaluate_retroactive=AsyncMock(return_value=list(_MOCK_SHADOW_STRUCTURAL_TAGS)),
        )
        jetstream = SimpleNamespace(publish=AsyncMock())
        deps = OutboxProcessorDeps(
            session_factory=fac,
            graph_client=NullGraphClient(),
            redis_client=None,
            shadow_runtime=runtime,
            nats_jetstream=jetstream,
        )

        stats = await process_outbox_batch(deps, batch_size=10)

        assert stats.claimed == 1
        assert stats.completed == 1
        assert stats.failed == 0
        jetstream.publish.assert_awaited_once()

        async with fac() as session:
            label_row = await session.scalar(
                select(NormalizedLabelORM).where(NormalizedLabelORM.source_id == event_id),
            )
            assert label_row is not None
            assert label_row.propagated_to_consortium is True
            for tag in _MOCK_SHADOW_STRUCTURAL_TAGS:
                assert tag in label_row.tags

        await engine.dispose()

    asyncio.run(_run())
