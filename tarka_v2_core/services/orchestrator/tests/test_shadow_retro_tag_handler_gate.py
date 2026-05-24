"""Gate: ``SHADOW_RETRO_TAG`` outbox handler persists normalized labels from Shadow retro tags."""

from __future__ import annotations

import asyncio
import json
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

_SRC_ORCH = Path(__file__).resolve().parents[1] / "src"
_SRC_INGESTOR = Path(__file__).resolve().parents[2] / "ingestor" / "src"
_SRC_SHARED = Path(__file__).resolve().parents[2] / "shared"
_SRC_SERVICES = Path(__file__).resolve().parents[2]
_SRC_SHADOW = Path(__file__).resolve().parents[2] / "shadow_agent" / "src"
for _p in (_SRC_ORCH, _SRC_INGESTOR, _SRC_SHARED, _SRC_SERVICES, _SRC_SHADOW):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

_MOCK_TAGS = ["vector:ato", "matched_rule:velocity_ip", "ground_truth:fraud"]


def test_shadow_retro_tag_handler_queries_clickhouse_and_persists_label() -> None:
    async def _run() -> None:
        from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
        from sqlalchemy.pool import StaticPool

        import orchestrator.models.cases  # noqa: F401
        import orchestrator.models.decision  # noqa: F401
        import orchestrator.models.label_dlq  # noqa: F401
        import orchestrator.models.normalized_labels  # noqa: F401
        import orchestrator.models.operational_signals  # noqa: F401
        import orchestrator.models.outbox  # noqa: F401
        import tarka_shared.audit_trail  # noqa: F401
        import tarka_shared.engine_rules  # noqa: F401
        import tarka_shared.fraud_rules  # noqa: F401

        from orchestrator.audit_case_worker import ORCHESTRATOR_AUDIT_SOURCE
        from orchestrator.graph.client import NullGraphClient
        from orchestrator.models.cases import CaseORM, CaseStatus
        from orchestrator.models.decision import DecisionORM
        from orchestrator.models.normalized_labels import NormalizedLabelORM, SOURCE_TYPE_CHARGEBACK
        from orchestrator.models.operational_signals import OperationalSignalORM
        from orchestrator.models.outbox import OUTBOX_EVENT_SHADOW_RETRO_TAG, OutboxDAO, OutboxORM
        from orchestrator.workers.handlers.base import OutboxProcessorDeps
        from orchestrator.workers.handlers.shadow_retro_tag import ShadowRetroTagHandler
        from tarka_shared.audit_trail import AuditLog, Case
        from tarka_shared.case_status import DEFAULT_CASE_STATUS
        from tarka_shared.data.tenant_constants import DEFAULT_TENANT_ID
        from tarka_shared.database.session import Base

        entity_id = str(uuid.uuid4())
        signal_id = uuid.uuid4()
        shadow_case_id = str(uuid.uuid4())
        case_uuid = str(uuid.uuid4())

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
                                "amount": 99.0,
                                "timestamp": "2026-05-09T12:00:00+00:00",
                                "metadata": {"user_id": "u-shadow-retro"},
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
                        user_link_key="u-shadow-retro",
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
                        raw_rule_engine_json={"transaction_id": entity_id},
                    ),
                )
                session.add(
                    OperationalSignalORM(
                        id=signal_id,
                        idempotency_key="cb:shadow-retro:4853",
                        target_entity_id=entity_id,
                        signal_type="CHARGEBACK_RECEIVED",
                        metadata_json={
                            "amount_cents": 9900,
                            "currency": "USD",
                            "chargeback_reason_code": "4853",
                            "card_network": "VISA",
                        },
                    ),
                )
                await OutboxDAO.create_task(
                    session,
                    OUTBOX_EVENT_SHADOW_RETRO_TAG,
                    f"shadow_tag_ops:cb:shadow-retro:4853",
                    {
                        "entity_id": entity_id,
                        "signal_id": str(signal_id),
                        "metadata": {
                            "amount_cents": 9900,
                            "currency": "USD",
                            "chargeback_reason_code": "4853",
                            "card_network": "VISA",
                        },
                    },
                )

        ch_client = SimpleNamespace()
        ch_client.query = lambda *_args, **_kwargs: SimpleNamespace(
            result_rows=[
                (
                    entity_id,
                    [{"rule_id": "velocity_ip", "matched": True}],
                    {"entity_id": entity_id},
                    "0.1.0",
                    1,
                    0,
                    100,
                ),
            ],
            column_names=[
                "manifest_id",
                "trace_json",
                "signals",
                "engine_version",
                "timestamp_ns",
                "final_decision",
                "total_execution_time_us",
            ],
        )

        evaluate_mock = AsyncMock(return_value=list(_MOCK_TAGS))
        runtime = SimpleNamespace(evaluate_retroactive=evaluate_mock)
        jetstream = SimpleNamespace(publish=AsyncMock())

        handler = ShadowRetroTagHandler(
            OutboxProcessorDeps(
                session_factory=fac,
                graph_client=NullGraphClient(),
                redis_client=None,
                clickhouse_client=ch_client,
                shadow_runtime=runtime,
                nats_jetstream=jetstream,
            ),
        )

        async with fac() as session:
            outbox_row = await session.scalar(select(OutboxORM))
        assert outbox_row is not None

        await handler.execute(dict(outbox_row.payload))

        evaluate_mock.assert_awaited_once()
        manifest_arg, feedback_arg = evaluate_mock.await_args.args
        assert manifest_arg["trace_steps"]
        assert feedback_arg["ground_truth_class"] == "FRAUD"
        assert feedback_arg["operational_metadata"]["chargeback_reason_code"] == "4853"

        async with fac() as session:
            label_row = await session.scalar(
                select(NormalizedLabelORM).where(NormalizedLabelORM.source_id == signal_id),
            )
        assert label_row is not None
        assert label_row.source_type == SOURCE_TYPE_CHARGEBACK
        assert label_row.ground_truth_class == "FRAUD"
        assert label_row.propagated_to_consortium is True
        for tag in _MOCK_TAGS:
            assert tag in label_row.tags

        jetstream.publish.assert_awaited_once()
        await engine.dispose()

    asyncio.run(_run())
