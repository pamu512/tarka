"""Gate (Prompt 125): delivery confirmation audit alignment + ≥10 same-IP successes → friendly fraud flag."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import tarka_shared.audit_trail  # noqa: F401
from ingestor.schemas import TransactionSchema
from shadow_agent.agent import ShadowAgent, _ensure_case_for_shadow_audit
from shadow_agent.schemas import ShadowDecision
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool
from tarka_shared.audit_trail import AuditLog, Case
from tarka_shared.case_status import DEFAULT_CASE_STATUS
from tarka_shared.data.tenant_constants import DEFAULT_TENANT_ID
from tarka_shared.database.session import Base

_SHARED_IP = "203.0.113.50"
_POD_HASH = "a" * 64


def _order_audit_payload(*, amount: float) -> str:
    return json.dumps(
        {
            "transaction_id": str(uuid4()),
            "amount": amount,
            "is_fraud": False,
            "ip_address": _SHARED_IP,
            "investigation_case_number": f"ORD-{uuid4().hex[:8]}",
            "case_outcome": "DELIVERED",
        },
        separators=(",", ":"),
    )


class _StubLlmHighRisk:
    """Returns an adversarial fraud JSON so post-rules must enforce friendly-fraud disposition."""

    def __init__(self) -> None:
        self.calls: list[list[dict[str, str]]] = []

    async def chat_json_validated(
        self,
        messages: list[dict[str, str]],
        *_args: object,
        **_kwargs: object,
    ) -> dict[str, object]:
        self.calls.append(messages)
        tid = None
        for line in messages[0]["content"].splitlines():
            if "entity_id (canonical transaction id" in line:
                tid = line.split(":")[-1].strip()
                break
        assert tid
        return {
            "transaction_id": tid,
            "risk_score": 88.0,
            "is_fraud": True,
            "reasoning": ["synthetic high risk"],
            "confidence_metrics": {"p_fraud": 0.9},
            "ai_reasoning": "LLM says fraud",
        }


def test_friendly_fraud_flags_after_ten_same_ip_orders_and_delivery_audit_alignment() -> None:
    dispute_id = UUID("cccccccc-cccc-cccc-cccc-cccccccccccc")
    dispute_ts = datetime(2026, 6, 15, 18, 0, 0, tzinfo=UTC)
    pod_ts_iso = "2026-06-15T17:00:00+00:00"

    tx = TransactionSchema(
        entity_id=dispute_id,
        amount=199.0,
        timestamp=dispute_ts,
        metadata={
            "ip_address": _SHARED_IP,
            "delivery_confirmation_hash": _POD_HASH,
            "ingestion_type": "CHARGEBACK",
        },
    )

    llm = _StubLlmHighRisk()
    agent = ShadowAgent(llm_client=llm)  # type: ignore[arg-type]

    async def _run() -> ShadowDecision:
        engine = create_async_engine(
            "sqlite+aiosqlite:///:memory:",
            poolclass=StaticPool,
            connect_args={"check_same_thread": False},
        )
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        fac = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
        async with fac() as session:
            for i in range(11):
                cid = str(uuid4())
                session.add(
                    Case(
                        id=cid,
                        tenant_id=DEFAULT_TENANT_ID,
                        name=f"prior-order-{i}",
                        dataset_path=None,
                        is_active=False,
                        status=DEFAULT_CASE_STATUS,
                    ),
                )
                session.add(
                    AuditLog(
                        case_id=cid,
                        action_taken=_order_audit_payload(amount=10.0 + i),
                        code_executed=None,
                        agent_notes=None,
                        timestamp=dispute_ts - timedelta(days=i + 2),
                    ),
                )

            await _ensure_case_for_shadow_audit(session, str(dispute_id))
            session.add(
                AuditLog(
                    case_id=str(dispute_id),
                    action_taken=json.dumps({"transaction_id": str(dispute_id), "amount": 199.0}),
                    code_executed=json.dumps(
                        {
                            "carrier_pod": {
                                "delivery_confirmation_hash": _POD_HASH,
                                "delivery_confirmation_at": pod_ts_iso,
                            },
                        },
                        separators=(",", ":"),
                    ),
                    agent_notes=None,
                    timestamp=dispute_ts - timedelta(hours=1),
                ),
            )
            await session.commit()

            out, _audit = await agent.evaluate(tx, session)
            n = (await session.execute(select(func.count()).select_from(AuditLog))).scalar_one()
            assert int(n) >= 13
        await engine.dispose()
        return out

    decision = asyncio.run(_run())
    assert decision.confidence_metrics.get("dispute_classification") == "FRIENDLY_FRAUD"
    assert int(decision.confidence_metrics.get("prior_successful_orders_same_ip") or 0) >= 10
    assert decision.confidence_metrics.get("delivery_confirmation_timestamp_aligned") is True
    assert decision.confidence_metrics.get("delivery_confirmation_hash_seen_in_audit") is True
    assert decision.is_fraud is False
    assert decision.risk_score <= 25.0
    assert "Friendly fraud" in decision.ai_reasoning

    prompt = llm.calls[0][0]["content"]
    assert "friendly_fraud_signals" in prompt
    assert "FRIENDLY FRAUD" in prompt
    assert "prior_successful_orders_same_ip" in prompt
