"""Gate: three BLOCK ingests for the same user_id → one lifecycle case, three case_history rows."""

from __future__ import annotations

import asyncio
import sys
import uuid
from pathlib import Path

from sqlalchemy import func, select

_SRC_ORCH = Path(__file__).resolve().parents[1] / "src"
_SRC_INGESTOR = Path(__file__).resolve().parents[2] / "ingestor" / "src"
_SRC_SHARED = Path(__file__).resolve().parents[2] / "shared"
for _p in (_SRC_ORCH, _SRC_INGESTOR, _SRC_SHARED):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


def test_three_fraudulent_transactions_same_user_id_one_case_three_history_rows() -> None:
    async def _run() -> None:
        import orchestrator.models.cases  # noqa: F401, PLC0415
        import tarka_shared.audit_trail  # noqa: F401, PLC0415
        import tarka_shared.engine_rules  # noqa: F401, PLC0415
        from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
        from sqlalchemy.pool import StaticPool
        from tarka_shared.database.session import Base

        from orchestrator.audit_case_worker import (
            persist_orchestrator_audit_log,
            run_audit_poll_once,
        )
        from orchestrator.models.cases import CaseHistoryORM, CaseORM

        url = "sqlite+aiosqlite:///:memory:"
        engine = create_async_engine(
            url,
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        fac = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        user_id = "fraud-user-gate-77"
        for _ in range(3):
            eid = str(uuid.uuid4())
            async with fac() as session:
                async with session.begin():
                    await persist_orchestrator_audit_log(
                        session,
                        entity_id=eid,
                        metadata={"user_id": user_id, "channel": "card_not_present"},
                        actions=["BLOCK", "FLAG"],
                        rule_data={"actions": ["BLOCK"], "risk_score": 88.0},
                        shadow_data=None,
                    )

        await run_audit_poll_once(fac)

        async with fac() as session:
            n_cases = int(
                await session.scalar(select(func.count()).select_from(CaseORM)),
            )
            n_hist = int(
                await session.scalar(select(func.count()).select_from(CaseHistoryORM)),
            )
            rows = (await session.scalars(select(CaseHistoryORM.audit_log_id))).all()

        assert n_cases == 1
        assert n_hist == 3
        assert len(set(rows)) == 3

        await engine.dispose()

    asyncio.run(_run())
