"""Gate (Prompt 191): ``audit_logs.shadow_matches`` stores fired shadow hypothesis rules per transaction."""

from __future__ import annotations

import asyncio
import json
import sys
import uuid
from pathlib import Path

from sqlalchemy import select

_SRC_ORCH = Path(__file__).resolve().parents[1] / "src"
_SRC_INGESTOR = Path(__file__).resolve().parents[2] / "ingestor" / "src"
_SRC_SHARED = Path(__file__).resolve().parents[2] / "shared"
_REPO = Path(__file__).resolve().parents[3]
for _p in (_SRC_ORCH, _SRC_INGESTOR, _SRC_SHARED, _REPO):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


def test_persist_orchestrator_audit_log_writes_shadow_matches_column() -> None:
    async def _run() -> None:
        import orchestrator.models.cases  # noqa: F401, PLC0415
        import tarka_shared.audit_trail  # noqa: F401, PLC0415
        from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
        from sqlalchemy.pool import StaticPool
        from tarka_shared.audit_trail import AuditLog
        from tarka_shared.database.session import Base

        from orchestrator.audit_case_worker import persist_orchestrator_audit_log

        engine = create_async_engine(
            "sqlite+aiosqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        fac = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        eid = str(uuid.uuid4())
        shadow_matches = [
            {
                "rule_id": "shadow_probe",
                "matched": True,
                "recorded_at": "2026-05-18T12:00:00+00:00",
            },
        ]
        async with fac() as session:
            async with session.begin():
                log_id = await persist_orchestrator_audit_log(
                    session,
                    entity_id=eid,
                    metadata={"user_id": "u-shadow-audit"},
                    actions=[],
                    rule_data={"actions": []},
                    shadow_data=None,
                    shadow_matches=shadow_matches,
                )
        assert log_id > 0

        async with fac() as session:
            row = await session.scalar(select(AuditLog).where(AuditLog.id == log_id))
        assert row is not None
        assert row.shadow_matches == shadow_matches

        await engine.dispose()

    asyncio.run(_run())


def test_evaluate_transaction_shadow_matches_from_redis() -> None:
    async def _run() -> None:
        from datetime import UTC, datetime
        from uuid import UUID

        from fakeredis import FakeAsyncRedis
        from ingestor.manifest_schema import TransactionSchema
        from tarka_v2_core.shadow_hypothesis import SHADOW_RULES_ACTIVE_KEY

        from orchestrator.shadow_hypothesis_audit import evaluate_transaction_shadow_matches

        redis = FakeAsyncRedis(decode_responses=True)
        rules = [
            {
                "id": "shadow_lane",
                "metadata": {"is_shadow": True},
                "when": [{"op": "contains", "field": "lane", "value": "STRESS"}],
            },
        ]
        await redis.set(SHADOW_RULES_ACTIVE_KEY, json.dumps(rules))

        class _State:
            pass

        st = _State()
        st.shadow_rules_redis = redis

        tx = TransactionSchema.model_validate(
            {
                "entity_id": str(UUID("11111111-2222-3333-4444-555555555555")),
                "amount": 50.0,
                "timestamp": datetime.now(UTC).isoformat(),
                "metadata": {"lane": "STRESS_BLOCK_LANE"},
            },
        )
        matches = await evaluate_transaction_shadow_matches(st, tx)
        assert len(matches) == 1
        assert matches[0]["rule_id"] == "shadow_lane"
        assert matches[0]["matched"] is True

    asyncio.run(_run())
