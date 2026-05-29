"""Gate: LABEL_PROPAGATE outbox handler + label propagation helpers."""

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


def test_structural_tags_from_evidence_and_disposition() -> None:
    from orchestrator.label_propagation import (
        EvidenceManifestSnapshot,
        structural_tags_from_evidence_and_disposition,
    )
    from orchestrator.utils.entity_parser import parse_entities

    text = "Chargeback ORD-12345678 for duplicate billing. Tracking 92612901001234567890123456"
    parsed = parse_entities(text)
    evidence = EvidenceManifestSnapshot(
        manifest_id="manifest-abc",
        trace_steps=(
            {"rule_id": "velocity_ip", "matched": True},
            {"rule_id": "amount_cap", "matched": False},
        ),
    )
    tags = structural_tags_from_evidence_and_disposition(
        ground_truth_class="FRAUD",
        disposition_text=text,
        evidence=evidence,
        parsed=parsed,
        shadow_reasoning=["SYNTHETIC_IDENTITY_PATTERN"],
    )
    assert "ground_truth:FRAUD" in tags
    assert "manifest:manifest-abc" in tags
    assert "matched_rule:velocity_ip" in tags
    assert "shadow_reason:SYNTHETIC_IDENTITY_PATTERN" in tags


def test_label_propagator_handler_runs_retroactive_label_and_publishes_jetstream() -> None:
    async def _run() -> None:
        from unittest.mock import patch

        from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
        from sqlalchemy.pool import StaticPool

        import orchestrator.models.cases  # noqa: F401
        import orchestrator.models.decision  # noqa: F401
        import orchestrator.models.label_dlq  # noqa: F401
        import orchestrator.models.normalized_labels  # noqa: F401
        import orchestrator.models.outbox  # noqa: F401
        import tarka_shared.audit_trail  # noqa: F401
        import tarka_shared.engine_rules  # noqa: F401
        import tarka_shared.fraud_rules  # noqa: F401

        from orchestrator.audit_case_worker import ORCHESTRATOR_AUDIT_SOURCE
        from orchestrator.graph.client import NullGraphClient
        from orchestrator.label_propagation import build_label_propagate_payload
        from orchestrator.messaging.labels_jetstream import TARKA_LABELS_SUBJECT
        from orchestrator.models.cases import CaseORM, CaseStatus
        from orchestrator.models.decision import DecisionORM
        from orchestrator.models.normalized_labels import GroundTruthClass, NormalizedLabelDAO
        from orchestrator.models.outbox import OUTBOX_EVENT_LABEL_PROPAGATE, OutboxDAO
        from orchestrator.workers.handlers.base import OutboxProcessorDeps
        from orchestrator.workers.handlers.label_propagator import LabelPropagatorHandler
        from tarka_shared.audit_trail import AuditLog, Case
        from tarka_shared.case_status import DEFAULT_CASE_STATUS
        from tarka_shared.data.tenant_constants import DEFAULT_TENANT_ID
        from tarka_shared.database.session import Base

        entity_id = str(uuid.uuid4())
        shadow_case_id = str(uuid.uuid4())
        case_uuid = str(uuid.uuid4())
        retro_tags = [
            "ground_truth:fraud",
            "vector:chargeback",
            "matched_rule:velocity_ip",
        ]

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
                                "amount": 42.0,
                                "timestamp": "2026-05-09T12:00:00+00:00",
                                "metadata": {
                                    "user_id": "u-label-prop",
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
                        user_link_key="u-label-prop",
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
                        execution_trace_json=[
                            {"rule_id": "velocity_ip", "matched": True},
                        ],
                        blocking_rule_id=None,
                        raw_rule_engine_json={
                            "transaction_id": entity_id,
                            "evaluation_trace": [
                                {"rule_id": "velocity_ip", "matched": True},
                            ],
                        },
                    ),
                )
                label_row = await NormalizedLabelDAO.create_analyst_disposition(
                    session,
                    case_history_id=99,
                    entity_id=entity_id,
                    ground_truth_class=GroundTruthClass.FRAUD,
                    reason_code="GATE_ANALYST_FINAL",
                    resolved_status=CaseStatus.RESOLVED_FRAUD.value,
                )
                payload = build_label_propagate_payload(
                    normalized_label_id=label_row.id,
                    entity_id=entity_id,
                    source_type=label_row.source_type,
                    source_id=label_row.source_id,
                    ground_truth_class=label_row.ground_truth_class,
                    disposition_text="Chargeback ORD-12345678 duplicate billing",
                    case_history_id=99,
                    audit_log_id=int(ingest_log.id),
                )
                await OutboxDAO.create_task(
                    session,
                    OUTBOX_EVENT_LABEL_PROPAGATE,
                    f"label_propagate:{label_row.id}",
                    payload,
                )
                label_id = label_row.id

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
            new=AsyncMock(return_value=retro_tags),
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
        retro_args = retro_mock.await_args.args
        assert retro_args[1]["ground_truth_class"] == "FRAUD"
        assert retro_args[0]["trace_steps"]

        jetstream.publish.assert_awaited_once()
        publish_args = jetstream.publish.await_args
        assert publish_args.args[0] == TARKA_LABELS_SUBJECT
        published = json.loads(publish_args.args[1].decode("utf-8"))
        assert published["schema"] == "tarka.normalized_label.v1"
        assert published["id"] == str(label_id)
        assert published["entity_id"] == entity_id
        assert published["propagated_to_consortium"] is True
        for tag in retro_tags:
            assert tag in published["tags"]
        assert "analyst_disposition" not in published["tags"]

        async with fac() as session:
            from orchestrator.models.normalized_labels import NormalizedLabelORM

            row = await session.get(NormalizedLabelORM, label_id)
            assert row is not None
            assert row.propagated_to_consortium is True
            for tag in retro_tags:
                assert tag in row.tags

        await engine.dispose()

    asyncio.run(_run())


def test_label_propagator_shadow_eval_retries_then_succeeds() -> None:
    async def _run() -> None:
        from unittest.mock import patch

        from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
        from sqlalchemy.pool import StaticPool

        import orchestrator.models.cases  # noqa: F401
        import orchestrator.models.decision  # noqa: F401
        import orchestrator.models.label_dlq  # noqa: F401
        import orchestrator.models.normalized_labels  # noqa: F401
        import orchestrator.models.outbox  # noqa: F401
        import tarka_shared.audit_trail  # noqa: F401
        import tarka_shared.engine_rules  # noqa: F401
        import tarka_shared.fraud_rules  # noqa: F401
        from shadow_agent.llm_client import ShadowLLMError

        from orchestrator.audit_case_worker import ORCHESTRATOR_AUDIT_SOURCE
        from orchestrator.graph.client import NullGraphClient
        from orchestrator.label_propagation import build_label_propagate_payload
        from orchestrator.models.cases import CaseORM, CaseStatus
        from orchestrator.models.decision import DecisionORM
        from orchestrator.models.normalized_labels import GroundTruthClass, NormalizedLabelDAO
        from orchestrator.models.outbox import OUTBOX_EVENT_LABEL_PROPAGATE, OutboxDAO
        from orchestrator.workers.handlers.base import OutboxProcessorDeps
        from orchestrator.workers.handlers.label_propagator import LabelPropagatorHandler
        from tarka_shared.audit_trail import AuditLog, Case
        from tarka_shared.case_status import DEFAULT_CASE_STATUS
        from tarka_shared.data.tenant_constants import DEFAULT_TENANT_ID
        from tarka_shared.database.session import Base

        entity_id = str(uuid.uuid4())
        shadow_case_id = str(uuid.uuid4())
        case_uuid = str(uuid.uuid4())
        retro_tags = ["ground_truth:fraud", "vector:chargeback"]
        attempt = {"count": 0}

        engine = create_async_engine(
            "sqlite+aiosqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        fac = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
        payload, label_id = await _seed_label_propagate_fixture(
            fac=fac,
            entity_id=entity_id,
            shadow_case_id=shadow_case_id,
            case_uuid=case_uuid,
            reason_code="GATE_RETRY_OK",
            case_history_id=102,
        )

        async def _evaluate_side_effect(*_args, **_kwargs):
            attempt["count"] += 1
            if attempt["count"] < 3:
                raise ShadowLLMError("ollama timeout", reason="timeout")
            return retro_tags

        async def _run_inference(fn):
            return await fn()

        runtime = SimpleNamespace(
            llm_client=SimpleNamespace(),
            gateway=SimpleNamespace(
                run_shadow_investigate_inference=AsyncMock(side_effect=_run_inference),
            ),
        )
        jetstream = SimpleNamespace(publish=AsyncMock())

        with (
            patch(
                "shadow_agent.retroactive_label.evaluate_retroactive_label",
                new=AsyncMock(side_effect=_evaluate_side_effect),
            ),
            patch("asyncio.sleep", new=AsyncMock()),
        ):
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

        assert attempt["count"] == 3
        jetstream.publish.assert_awaited_once()
        published = json.loads(jetstream.publish.await_args.args[1].decode("utf-8"))
        for tag in retro_tags:
            assert tag in published["tags"]

        async with fac() as session:
            from orchestrator.models.normalized_labels import NormalizedLabelORM

            row = await session.get(NormalizedLabelORM, label_id)
            assert row is not None
            assert row.propagated_to_consortium is True

        await engine.dispose()

    asyncio.run(_run())


def test_label_propagator_shadow_eval_exhausted_uses_placeholder_tag() -> None:
    async def _run() -> None:
        from unittest.mock import patch

        from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
        from sqlalchemy.pool import StaticPool

        import orchestrator.models.cases  # noqa: F401
        import orchestrator.models.decision  # noqa: F401
        import orchestrator.models.label_dlq  # noqa: F401
        import orchestrator.models.normalized_labels  # noqa: F401
        import orchestrator.models.outbox  # noqa: F401
        import tarka_shared.audit_trail  # noqa: F401
        import tarka_shared.engine_rules  # noqa: F401
        import tarka_shared.fraud_rules  # noqa: F401
        from shadow_agent.llm_client import ShadowLLMError

        from orchestrator.graph.client import NullGraphClient
        from orchestrator.models.label_dlq import TarkaLabelDlqORM
        from orchestrator.workers.handlers.base import OutboxProcessorDeps
        from orchestrator.workers.handlers.label_propagator import (
            SHADOW_EVALUATION_FAILED_PLACEHOLDER_TAG,
            LabelPropagatorHandler,
            _SHADOW_EVAL_MAX_RETRIES,
        )

        import orchestrator.models.cases  # noqa: F401
        import orchestrator.models.decision  # noqa: F401
        import orchestrator.models.label_dlq  # noqa: F401
        import orchestrator.models.normalized_labels  # noqa: F401
        import orchestrator.models.outbox  # noqa: F401
        import tarka_shared.audit_trail  # noqa: F401
        import tarka_shared.engine_rules  # noqa: F401
        import tarka_shared.fraud_rules  # noqa: F401
        from tarka_shared.database.session import Base

        entity_id = str(uuid.uuid4())
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
        payload, label_id = await _seed_label_propagate_fixture(
            fac=fac,
            entity_id=entity_id,
            shadow_case_id=shadow_case_id,
            case_uuid=case_uuid,
            reason_code="GATE_SHADOW_FALLBACK",
            case_history_id=103,
        )

        async def _run_inference(fn):
            return await fn()

        runtime = SimpleNamespace(
            llm_client=SimpleNamespace(),
            gateway=SimpleNamespace(
                run_shadow_investigate_inference=AsyncMock(side_effect=_run_inference),
            ),
        )
        jetstream = SimpleNamespace(publish=AsyncMock())
        retro_mock = AsyncMock(
            side_effect=ShadowLLMError("sidecar crashed", reason="sidecar_crash"),
        )

        with (
            patch("shadow_agent.retroactive_label.evaluate_retroactive_label", new=retro_mock),
            patch("asyncio.sleep", new=AsyncMock()),
        ):
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

        assert retro_mock.await_count == _SHADOW_EVAL_MAX_RETRIES + 1
        jetstream.publish.assert_awaited_once()
        published = json.loads(jetstream.publish.await_args.args[1].decode("utf-8"))
        assert SHADOW_EVALUATION_FAILED_PLACEHOLDER_TAG in published["tags"]

        async with fac() as session:
            dlq_rows = (await session.scalars(select(TarkaLabelDlqORM))).all()
            assert dlq_rows == []

            from orchestrator.models.normalized_labels import NormalizedLabelORM

            row = await session.get(NormalizedLabelORM, label_id)
            assert row is not None
            assert row.propagated_to_consortium is True
            assert SHADOW_EVALUATION_FAILED_PLACEHOLDER_TAG in row.tags

        await engine.dispose()

    asyncio.run(_run())


async def _seed_label_propagate_fixture(
    *,
    fac,
    entity_id: str,
    shadow_case_id: str,
    case_uuid: str,
    reason_code: str,
    case_history_id: int,
):
    from orchestrator.audit_case_worker import ORCHESTRATOR_AUDIT_SOURCE
    from orchestrator.label_propagation import build_label_propagate_payload
    from orchestrator.models.cases import CaseORM, CaseStatus
    from orchestrator.models.decision import DecisionORM
    from orchestrator.models.normalized_labels import GroundTruthClass, NormalizedLabelDAO
    from orchestrator.models.outbox import OUTBOX_EVENT_LABEL_PROPAGATE, OutboxDAO
    from tarka_shared.audit_trail import AuditLog, Case
    from tarka_shared.case_status import DEFAULT_CASE_STATUS
    from tarka_shared.data.tenant_constants import DEFAULT_TENANT_ID

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
                            "amount": 42.0,
                            "timestamp": "2026-05-09T12:00:00+00:00",
                            "metadata": {"user_id": "u-label-prop"},
                        },
                    },
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
                    user_link_key="u-label-prop",
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
                    raw_rule_engine_json={"transaction_id": entity_id, "evaluation_trace": []},
                ),
            )
            label_row = await NormalizedLabelDAO.create_analyst_disposition(
                session,
                case_history_id=case_history_id,
                entity_id=entity_id,
                ground_truth_class=GroundTruthClass.FRAUD,
                reason_code=reason_code,
                resolved_status=CaseStatus.RESOLVED_FRAUD.value,
            )
            payload = build_label_propagate_payload(
                normalized_label_id=label_row.id,
                entity_id=entity_id,
                source_type=label_row.source_type,
                source_id=label_row.source_id,
                ground_truth_class=label_row.ground_truth_class,
                disposition_text="Chargeback duplicate billing",
                case_history_id=case_history_id,
                audit_log_id=int(ingest_log.id),
            )
            await OutboxDAO.create_task(
                session,
                OUTBOX_EVENT_LABEL_PROPAGATE,
                f"label_propagate:{label_row.id}",
                payload,
            )
            return payload, label_row.id


def test_label_propagator_routes_invalid_structural_tags_to_dlq() -> None:
    async def _run() -> None:
        from unittest.mock import patch

        from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
        from sqlalchemy.pool import StaticPool

        import orchestrator.models.cases  # noqa: F401
        import orchestrator.models.decision  # noqa: F401
        import orchestrator.models.label_dlq  # noqa: F401
        import orchestrator.models.normalized_labels  # noqa: F401
        import orchestrator.models.outbox  # noqa: F401
        import tarka_shared.audit_trail  # noqa: F401
        import tarka_shared.engine_rules  # noqa: F401
        import tarka_shared.fraud_rules  # noqa: F401

        from orchestrator.audit_case_worker import ORCHESTRATOR_AUDIT_SOURCE
        from orchestrator.graph.client import NullGraphClient
        from orchestrator.label_propagation import build_label_propagate_payload
        from orchestrator.models.cases import CaseORM, CaseStatus
        from orchestrator.models.decision import DecisionORM
        from orchestrator.models.label_dlq import TarkaLabelDlqORM
        from orchestrator.models.normalized_labels import GroundTruthClass, NormalizedLabelDAO
        from orchestrator.models.outbox import OUTBOX_EVENT_LABEL_PROPAGATE, OutboxDAO
        from orchestrator.workers.handlers.base import OutboxProcessorDeps
        from orchestrator.workers.handlers.label_propagator import LabelPropagatorHandler
        from tarka_shared.audit_trail import AuditLog, Case
        from tarka_shared.case_status import DEFAULT_CASE_STATUS
        from tarka_shared.data.tenant_constants import DEFAULT_TENANT_ID
        from tarka_shared.database.session import Base

        entity_id = str(uuid.uuid4())
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
                                "amount": 42.0,
                                "timestamp": "2026-05-09T12:00:00+00:00",
                                "metadata": {"user_id": "u-label-prop"},
                            },
                        },
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
                        user_link_key="u-label-prop",
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
                        raw_rule_engine_json={"transaction_id": entity_id, "evaluation_trace": []},
                    ),
                )
                label_row = await NormalizedLabelDAO.create_analyst_disposition(
                    session,
                    case_history_id=101,
                    entity_id=entity_id,
                    ground_truth_class=GroundTruthClass.FRAUD,
                    reason_code="GATE_DLQ",
                    resolved_status=CaseStatus.RESOLVED_FRAUD.value,
                )
                payload = build_label_propagate_payload(
                    normalized_label_id=label_row.id,
                    entity_id=entity_id,
                    source_type=label_row.source_type,
                    source_id=label_row.source_id,
                    ground_truth_class=label_row.ground_truth_class,
                    disposition_text="Chargeback duplicate billing",
                    case_history_id=101,
                    audit_log_id=int(ingest_log.id),
                )
                await OutboxDAO.create_task(
                    session,
                    OUTBOX_EVENT_LABEL_PROPAGATE,
                    f"label_propagate:{label_row.id}",
                    payload,
                )
                label_id = label_row.id

        async def _run_inference(fn):
            return await fn()

        runtime = SimpleNamespace(
            llm_client=SimpleNamespace(),
            gateway=SimpleNamespace(
                run_shadow_investigate_inference=AsyncMock(side_effect=_run_inference),
            ),
        )
        jetstream = SimpleNamespace(publish=AsyncMock())

        with patch.object(
            LabelPropagatorHandler,
            "_run_retroactive_label_evaluate",
            new=AsyncMock(return_value=["INVALID TAG", "vector:chargeback"]),
        ):
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

        jetstream.publish.assert_not_awaited()

        async with fac() as session:
            dlq_rows = (await session.scalars(select(TarkaLabelDlqORM))).all()
            assert len(dlq_rows) == 1
            assert dlq_rows[0].normalized_label_id == label_id
            assert dlq_rows[0].entity_id == entity_id
            assert (
                "INVALID TAG" in dlq_rows[0].rejection_reason
                or "must match" in dlq_rows[0].rejection_reason
            )

            from orchestrator.models.normalized_labels import NormalizedLabelORM

            row = await session.get(NormalizedLabelORM, label_id)
            assert row is not None
            assert row.propagated_to_consortium is False

        await engine.dispose()

    asyncio.run(_run())


def test_label_bus_emit_payload_validates_structural_tags() -> None:
    from orchestrator.schemas.label_bus import (
        LabelBusValidationError,
        validate_label_bus_emit_payload,
    )

    payload = {
        "schema": "tarka.normalized_label.v1",
        "id": str(uuid.uuid4()),
        "source_type": "ANALYST_DISPOSITION",
        "source_id": str(uuid.uuid4()),
        "entity_id": "entity-1",
        "ground_truth_class": "FRAUD",
        "tags": ["vector:chargeback", "matched_rule:velocity_ip"],
        "propagated_to_consortium": True,
        "created_at": "2026-05-01T00:00:00+00:00",
    }
    validated = validate_label_bus_emit_payload(payload)
    assert validated.entity_id == "entity-1"
    assert validated.tags == ["vector:chargeback", "matched_rule:velocity_ip"]

    bad = dict(payload)
    bad["tags"] = ["bad tag"]
    try:
        validate_label_bus_emit_payload(bad)
        raise AssertionError("expected validation failure")
    except LabelBusValidationError:
        pass


def test_case_transition_enqueues_label_propagate_outbox() -> None:
    import orchestrator.models.cases  # noqa: F401
    import orchestrator.models.normalized_labels  # noqa: F401
    import orchestrator.models.outbox  # noqa: F401
    import tarka_shared.audit_trail  # noqa: F401
    import tarka_shared.engine_rules  # noqa: F401
    import tarka_shared.fraud_rules  # noqa: F401

    from starlette.testclient import TestClient

    from orchestrator.main import create_app  # noqa: E402
    from orchestrator.models.cases import CaseORM, CaseStatus  # noqa: E402
    from orchestrator.models.outbox import OUTBOX_EVENT_LABEL_PROPAGATE, OutboxORM  # noqa: E402
    from tarka_shared.audit_trail import AuditLog, Case  # noqa: E402
    from tarka_shared.case_status import DEFAULT_CASE_STATUS  # noqa: E402
    from tarka_shared.data.tenant_constants import DEFAULT_TENANT_ID  # noqa: E402

    case_uuid = str(uuid.uuid4())
    shadow_case_id = str(uuid.uuid4())
    entity_id = str(uuid.uuid4())

    app = create_app(
        rule_engine_url="http://rules.test",
        shadow_agent_url=None,
        audit_database_url="sqlite+aiosqlite:///:memory:",
    )

    async def _seed() -> None:
        fac = app.state.audit_session_factory
        assert fac is not None
        async with fac() as s:
            s.add(
                Case(
                    id=shadow_case_id,
                    tenant_id=DEFAULT_TENANT_ID,
                    name="shadow-anchor",
                    dataset_path=None,
                    is_active=False,
                    status=DEFAULT_CASE_STATUS,
                ),
            )
            log = AuditLog(
                case_id=shadow_case_id,
                action_taken=json.dumps(
                    {
                        "source": "orchestrator_orchestrate",
                        "entity_id": entity_id,
                        "transaction_envelope": {
                            "entity_id": entity_id,
                            "amount": 10.0,
                            "timestamp": "2026-05-09T12:00:00+00:00",
                            "metadata": {"user_id": "u1"},
                        },
                    },
                ),
                agent_notes=None,
                code_executed=None,
                timestamp=datetime(2026, 8, 1, 10, 0, 0, tzinfo=UTC),
            )
            s.add(log)
            await s.flush()
            s.add(
                CaseORM(
                    case_id=case_uuid,
                    transaction_id=int(log.id),
                    user_link_key="u1",
                    entity_id=entity_id,
                    status=CaseStatus.OPEN.value,
                    priority=1,
                ),
            )
            await s.commit()

    with TestClient(app) as client:
        asyncio.run(_seed())
        r = client.put(
            f"/v1/cases/{case_uuid}/status",
            json={"status": "RESOLVED_FRAUD", "reason_code": "GATE_FINAL_FRAUD"},
            headers={"X-Auth-Token": "gate-secret-token-labels"},
        )
        assert r.status_code == 200, r.text

        async def _count_outbox() -> int:
            fac = app.state.audit_session_factory
            assert fac is not None
            async with fac() as session:
                rows = (
                    await session.scalars(
                        select(OutboxORM).where(
                            OutboxORM.event_type == OUTBOX_EVENT_LABEL_PROPAGATE
                        ),
                    )
                ).all()
            assert len(rows) == 1
            assert rows[0].payload["schema"] == "tarka.label_propagate.v1"
            assert rows[0].payload["entity_id"] == entity_id
            return len(rows)

        assert asyncio.run(_count_outbox()) == 1
