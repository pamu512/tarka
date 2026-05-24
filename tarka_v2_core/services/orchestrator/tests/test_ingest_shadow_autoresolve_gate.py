"""Unit gate: inline autoresolve after ingest audit commit (no full FastAPI app import)."""

from __future__ import annotations

import asyncio
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from sqlalchemy import select

_SRC_ORCH = Path(__file__).resolve().parents[1] / "src"
_SRC_SHARED = Path(__file__).resolve().parents[2] / "shared"
_SRC_SERVICES = Path(__file__).resolve().parents[2]
for _p in (_SRC_ORCH, _SRC_SHARED, _SRC_SERVICES):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


def test_try_shadow_autoresolve_after_ingest_transitions_to_resolved_auto() -> None:
    async def _run() -> None:
        import orchestrator.models.cases  # noqa: F401, PLC0415
        import tarka_shared.audit_trail  # noqa: F401, PLC0415
        from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
        from sqlalchemy.pool import StaticPool
        from tarka_shared.audit_trail import AuditLog
        from tarka_shared.database.session import Base

        from orchestrator.audit_case_worker import persist_orchestrator_audit_log
        from orchestrator.models.cases import CaseHistoryORM, CaseORM, CaseStatus
        from orchestrator.shadow_autoresolve import try_shadow_autoresolve_after_ingest
        from shadow.hooks.resolve_case import CONFIDENCE_THRESHOLD

        url = "sqlite+aiosqlite:///:memory:"
        engine = create_async_engine(
            url,
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        fac = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        entity_id = str(uuid4())
        user_id = "u_inline_autoresolve"
        shadow_data = {
            "transaction_id": entity_id,
            "risk_score": 6.0,
            "is_fraud": False,
            "reasoning": ["pattern ok"],
            "confidence_metrics": {
                "confidence": min(1.0, CONFIDENCE_THRESHOLD + 0.02),
                "recommended_action": "AUTO_RESOLVE",
            },
            "ai_reasoning": "Machine cleared: benign merchant history.",
        }

        async with fac() as session:
            async with session.begin():
                audit_log_id = await persist_orchestrator_audit_log(
                    session,
                    entity_id=entity_id,
                    metadata={"user_id": user_id},
                    actions=["ALLOW"],
                    rule_data={"actions": ["ALLOW"], "risk_score": 12.0},
                    shadow_data=shadow_data,
                )

        out = await try_shadow_autoresolve_after_ingest(
            audit_session_factory=fac,
            graph_client=None,
            audit_log_id=audit_log_id,
            entity_id=entity_id,
            metadata={"user_id": user_id},
            actions=["ALLOW"],
            rule_data={"actions": ["ALLOW"], "risk_score": 12.0},
            shadow_data=shadow_data,
            auth_token="inline-autoresolve-token",
            lifecycle_actions=["FLAG"],
        )

        assert out.attempted is True
        assert out.skipped_reason is None
        assert out.lifecycle_case_id is not None
        assert out.transition is not None
        assert out.transition.get("status") == CaseStatus.RESOLVED_AUTO.value

        async with fac() as session:
            row = await session.scalar(
                select(CaseORM).where(CaseORM.case_id == out.lifecycle_case_id),
            )
            assert row is not None
            assert row.status == CaseStatus.RESOLVED_AUTO.value

            transition_audit_id = int(out.transition["audit_log_id"])
            tlog = await session.get(AuditLog, transition_audit_id)
            assert tlog is not None
            assert tlog.agent_notes is not None
            notes = json.loads(tlog.agent_notes)
            assert notes["source"] == "shadow_autoresolve"
            assert notes["ai_reasoning"] == shadow_data["ai_reasoning"]

            hist = (
                await session.scalars(
                    select(CaseHistoryORM).where(
                        CaseHistoryORM.case_id == out.lifecycle_case_id,
                        CaseHistoryORM.to_status == CaseStatus.RESOLVED_AUTO.value,
                    ),
                )
            ).all()
            assert len(hist) == 1
            assert hist[0].audit_log_id == transition_audit_id

        await engine.dispose()

    asyncio.run(_run())


def test_shadow_autoresolve_eligible_requires_confidence_above_threshold() -> None:
    from shadow.hooks.resolve_case import (
        CONFIDENCE_THRESHOLD,
        shadow_autoresolve_eligible,
    )

    ok, conf, skip = shadow_autoresolve_eligible(
        {
            "is_fraud": False,
            "risk_score": 5.0,
            "confidence_metrics": {"confidence": CONFIDENCE_THRESHOLD + 0.01},
        },
    )
    assert ok is True
    assert conf is not None
    assert skip is None

    blocked, _, reason = shadow_autoresolve_eligible(
        {
            "is_fraud": False,
            "risk_score": 5.0,
            "confidence_metrics": {"confidence": CONFIDENCE_THRESHOLD},
        },
    )
    assert blocked is False
    assert reason == "confidence_not_above_threshold"
