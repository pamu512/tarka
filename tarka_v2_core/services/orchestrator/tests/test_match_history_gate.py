"""
Gate (Prompt 121): ``match_history`` finds ``audit_logs`` by extracted tokens and returns transaction JSON.

Run::

    pytest tarka_v2_core/services/orchestrator/tests/test_match_history_gate.py -q
"""

from __future__ import annotations

import asyncio
import json
import sys
import uuid
from pathlib import Path

_SRC_ORCH = Path(__file__).resolve().parents[1] / "src"
_SRC_INGESTOR = Path(__file__).resolve().parents[2] / "ingestor" / "src"
_SRC_SHARED = Path(__file__).resolve().parents[2] / "shared"
for _p in (_SRC_ORCH, _SRC_INGESTOR, _SRC_SHARED):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


def test_order_id_finds_audit_row_and_returns_transaction_metadata() -> None:
    async def _run() -> None:
        import tarka_shared.audit_trail  # noqa: F401, PLC0415
        from orchestrator.disputes.match_history import find_audit_log_hits_for_tokens
        from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
        from sqlalchemy.pool import StaticPool
        from tarka_shared.audit_trail import AuditLog, Case
        from tarka_shared.case_status import DEFAULT_CASE_STATUS
        from tarka_shared.data.tenant_constants import DEFAULT_TENANT_ID
        from tarka_shared.database.session import Base

        engine = create_async_engine(
            "sqlite+aiosqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        fac = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        shadow_case_id = str(uuid.uuid4())
        entity_tx = str(uuid.uuid4())
        action = json.dumps(
            {
                "amount": 42.5,
                "transaction_id": entity_tx,
                "metadata": {"order_id": "ORD-11223344", "channel": "ecommerce"},
                "country": "US",
            },
            separators=(",", ":"),
        )

        async with fac() as s:
            s.add(
                Case(
                    id=shadow_case_id,
                    tenant_id=DEFAULT_TENANT_ID,
                    name="dispute-match-gate",
                    dataset_path=None,
                    is_active=False,
                    status=DEFAULT_CASE_STATUS,
                ),
            )
            s.add(
                AuditLog(
                    case_id=shadow_case_id,
                    action_taken=action,
                    agent_notes=None,
                    code_executed=None,
                ),
            )
            await s.commit()

        async with fac() as s:
            hits = await find_audit_log_hits_for_tokens(s, ["ORD-11223344"])

        assert len(hits) == 1
        assert hits[0].matched_tokens == ("ORD-11223344",)
        tx = hits[0].transaction
        assert tx is not None
        assert tx["metadata"]["order_id"] == "ORD-11223344"
        assert tx["amount"] == 42.5
        assert tx["transaction_id"] == entity_tx
        assert tx["metadata"]["channel"] == "ecommerce"

        await engine.dispose()

    asyncio.run(_run())


def test_tenant_filter_excludes_other_tenant_rows() -> None:
    async def _run() -> None:
        import tarka_shared.audit_trail  # noqa: F401, PLC0415
        from orchestrator.disputes.match_history import find_audit_log_hits_for_tokens
        from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
        from sqlalchemy.pool import StaticPool
        from tarka_shared.audit_trail import AuditLog, Case
        from tarka_shared.case_status import DEFAULT_CASE_STATUS
        from tarka_shared.data.tenant_constants import DEFAULT_TENANT_ID
        from tarka_shared.database.session import Base

        engine = create_async_engine(
            "sqlite+aiosqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        fac = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        case_a = str(uuid.uuid4())
        case_b = str(uuid.uuid4())
        payload = json.dumps(
            {
                "amount": 1.0,
                "transaction_id": str(uuid.uuid4()),
                "metadata": {"order_id": "ORD-99887766"},
            }
        )

        async with fac() as s:
            s.add(
                Case(
                    id=case_a,
                    tenant_id=DEFAULT_TENANT_ID,
                    name="a",
                    dataset_path=None,
                    is_active=False,
                    status=DEFAULT_CASE_STATUS,
                ),
            )
            s.add(
                Case(
                    id=case_b,
                    tenant_id="tenant_other",
                    name="b",
                    dataset_path=None,
                    is_active=False,
                    status=DEFAULT_CASE_STATUS,
                ),
            )
            s.add(AuditLog(case_id=case_a, action_taken=payload))
            s.add(AuditLog(case_id=case_b, action_taken=payload))
            await s.commit()

        async with fac() as s:
            hits_default = await find_audit_log_hits_for_tokens(
                s, ["ORD-99887766"], tenant_id=DEFAULT_TENANT_ID
            )

        assert len(hits_default) == 1
        assert hits_default[0].case_id == case_a

        await engine.dispose()

    asyncio.run(_run())
