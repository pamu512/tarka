"""Tests for :mod:`shadow_agent.history` entity audit projections."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta

import tarka_shared.audit_trail  # noqa: F401 — register ORM mappers
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool
from tarka_shared.audit_trail import AuditLog, Case
from tarka_shared.case_status import DEFAULT_CASE_STATUS
from tarka_shared.data.tenant_constants import DEFAULT_TENANT_ID
from tarka_shared.database.session import Base

from shadow_agent.history import RecentEntityTransaction, get_recent_entity_transactions


def test_get_recent_entity_transactions_returns_three_for_a123() -> None:
    """Gate: three seeded ``AuditLog`` rows for entity ``A123`` are returned as projections."""

    async def _run() -> list[RecentEntityTransaction]:
        engine = create_async_engine(
            "sqlite+aiosqlite:///:memory:",
            poolclass=StaticPool,
            connect_args={"check_same_thread": False},
        )
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        fac = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
        async with fac() as session:
            session.add(
                Case(
                    id="A123",
                    tenant_id=DEFAULT_TENANT_ID,
                    name="history-gate-case",
                    dataset_path=None,
                    is_active=False,
                    status=DEFAULT_CASE_STATUS,
                ),
            )
            base_ts = datetime(2026, 2, 1, 10, 0, 0, tzinfo=UTC)
            for i in range(3):
                session.add(
                    AuditLog(
                        case_id="A123",
                        action_taken=json.dumps(
                            {
                                "transaction_id": f"tx-{i}",
                                "amount": float(100 + i),
                                "is_fraud": i == 1,
                            },
                            separators=(",", ":"),
                        ),
                        code_executed=None,
                        agent_notes=None,
                        timestamp=base_ts + timedelta(minutes=i),
                    ),
                )
            await session.commit()

            rows = await get_recent_entity_transactions(session, "A123", 5)

        await engine.dispose()
        return rows

    rows = asyncio.run(_run())
    assert len(rows) == 3
    assert all(isinstance(r, RecentEntityTransaction) for r in rows)
    assert [r.amount for r in rows] == [102.0, 101.0, 100.0]
    assert [r.is_fraud for r in rows] == [False, True, False]
    assert rows[0].timestamp > rows[1].timestamp > rows[2].timestamp
