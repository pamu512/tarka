"""Gate: ``ShadowAgent.evaluate`` returns a validated ``ShadowDecision`` with mocked LLM."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import httpx
import pytest
import tarka_shared.audit_trail  # noqa: F401 — register ORM mappers
from ingestor.schemas import TransactionSchema
from shadow_agent.agent import ShadowAgent, _ensure_case_for_shadow_audit
from shadow_agent.llm_client import OllamaLLMClient
from shadow_agent.schemas import ShadowDecision
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool
from tarka_shared.audit_trail import AuditLog
from tarka_shared.database.session import Base


class _StubLlmClient:
    """Minimal stand-in for ``OllamaLLMClient.chat_json_validated``."""

    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload
        self.calls: list[list[dict[str, str]]] = []

    async def chat_json_validated(
        self,
        messages: list[dict[str, str]],
        *,
        model: str | None = None,
        json_self_correction_retries: int = 2,
    ) -> Any:
        self.calls.append(messages)
        return self._payload


def test_shadow_agent_evaluate_returns_shadow_decision(caplog: pytest.LogCaptureFixture) -> None:
    tx_id = UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
    tx = TransactionSchema(
        entity_id=tx_id,
        amount=42.0,
        timestamp=datetime(2026, 3, 1, 0, 0, 0, tzinfo=UTC),
        metadata={"k": "v"},
    )
    stub_payload: dict[str, Any] = {
        "transaction_id": str(tx_id),
        "risk_score": 37.5,
        "is_fraud": False,
        "reasoning": ["amount within baseline", "metadata consistent"],
        "confidence_metrics": {"p_fraud": 0.12},
    }
    llm = _StubLlmClient(stub_payload)
    agent = ShadowAgent(llm_client=llm)

    async def _run() -> tuple[ShadowDecision, AuditLog, int]:
        caplog.set_level(logging.INFO)
        engine = create_async_engine(
            "sqlite+aiosqlite:///:memory:",
            poolclass=StaticPool,
            connect_args={"check_same_thread": False},
        )
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        fac = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
        async with fac() as session:
            out, audit = await agent.evaluate(tx, session)
            n = (await session.execute(select(func.count()).select_from(AuditLog))).scalar_one()
        await engine.dispose()
        return out, audit, int(n)

    out, audit, row_count = asyncio.run(_run())
    assert isinstance(out, ShadowDecision)
    assert isinstance(audit, AuditLog)
    assert audit.id is not None
    assert row_count >= 1
    assert audit.case_id == str(tx_id)
    assert str(tx_id) in audit.code_executed
    assert '"is_fraud":false' in audit.action_taken
    assert "37.5" in audit.agent_notes
    assert out.transaction_id == tx_id
    assert out.risk_score == 37.5
    assert out.is_fraud is False
    assert len(out.reasoning) == 2
    assert out.confidence_metrics == {"p_fraud": 0.12}

    msgs = llm.calls[0]
    assert msgs[0]["role"] == "system"
    assert str(tx_id) in msgs[0]["content"]
    assert "42.0" in msgs[0]["content"] or repr(42.0) in msgs[0]["content"]

    log_text = " ".join(r.message for r in caplog.records)
    assert "shadow_evaluate_start" in log_text
    assert "shadow_evaluate_prompt_generated" in log_text
    assert "shadow_evaluate_llm_complete" in log_text
    assert "shadow_evaluate_validation_ok" in log_text
    assert "shadow_evaluate_audit_log_materialized" in log_text


def test_evaluate_httpx_micro_timeout_returns_timeout_fallback_instantly(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Gate: sub-millisecond httpx timeouts surface as a deterministic decision, not a 502."""

    def _raise_read_timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("simulated read timeout", request=request)

    transport = httpx.MockTransport(_raise_read_timeout)
    micro_timeout = httpx.Timeout(0.001)
    async_client = httpx.AsyncClient(
        transport=transport,
        base_url="http://127.0.0.1:11434",
        timeout=micro_timeout,
    )
    llm = OllamaLLMClient(
        client=async_client,
        max_retries=1,
        retry_wait_initial_sec=0.0,
        retry_wait_max_sec=0.0,
    )
    tx_id = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
    tx = TransactionSchema(
        entity_id=tx_id,
        amount=10.0,
        timestamp=datetime(2026, 3, 1, 0, 0, 0, tzinfo=UTC),
        metadata={},
    )
    agent = ShadowAgent(llm_client=llm)

    async def _run() -> tuple[ShadowDecision, AuditLog, float]:
        caplog.set_level(logging.WARNING)
        t0 = time.perf_counter()
        engine = create_async_engine(
            "sqlite+aiosqlite:///:memory:",
            poolclass=StaticPool,
            connect_args={"check_same_thread": False},
        )
        try:
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
            fac = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
            async with fac() as session:
                out, audit = await agent.evaluate(tx, session)
            elapsed = time.perf_counter() - t0
            return out, audit, elapsed
        finally:
            await llm.aclose()
            await engine.dispose()

    out, audit, elapsed_s = asyncio.run(_run())
    assert elapsed_s < 0.5, f"expected fast fallback, took {elapsed_s:.3f}s"
    assert out.transaction_id == tx_id
    assert out.risk_score == 0.0
    assert out.is_fraud is False
    assert out.reasoning == ["TIMEOUT_FALLBACK"]
    assert out.confidence_metrics == {}
    assert audit.case_id == str(tx_id)
    assert '"is_fraud":false' in audit.action_taken
    assert "timeout_fallback" in (audit.agent_notes or "")
    log_text = " ".join(r.message for r in caplog.records)
    assert "shadow_evaluate_ollama_timeout_fallback" in log_text


def test_evaluate_audit_log_code_executed_contains_entity_history_payload() -> None:
    """Gate: prior ``AuditLog`` rows for the entity appear inside persisted ``code_executed`` (raw prompt)."""
    tx_id = UUID("cccccccc-cccc-cccc-cccc-cccccccccccc")
    tx = TransactionSchema(
        entity_id=tx_id,
        amount=77.0,
        timestamp=datetime(2026, 6, 1, 15, 0, 0, tzinfo=UTC),
        metadata={"channel": "ach"},
    )
    stub_payload: dict[str, Any] = {
        "transaction_id": str(tx_id),
        "risk_score": 5.0,
        "is_fraud": False,
        "reasoning": ["history-aware stub"],
        "confidence_metrics": {"with_history": True},
    }
    llm = _StubLlmClient(stub_payload)
    agent = ShadowAgent(llm_client=llm)

    async def _run() -> AuditLog:
        engine = create_async_engine(
            "sqlite+aiosqlite:///:memory:",
            poolclass=StaticPool,
            connect_args={"check_same_thread": False},
        )
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        fac = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
        async with fac() as session:
            await _ensure_case_for_shadow_audit(session, str(tx_id))
            base_ts = datetime(2026, 5, 1, 12, 0, 0, tzinfo=UTC)
            for i, amt in enumerate((19.25, 31.5)):
                session.add(
                    AuditLog(
                        case_id=str(tx_id),
                        action_taken=json.dumps(
                            {
                                "transaction_id": str(tx_id),
                                "amount": amt,
                                "is_fraud": i == 0,
                            },
                            separators=(",", ":"),
                        ),
                        code_executed=None,
                        agent_notes=None,
                        timestamp=base_ts + timedelta(days=i),
                    ),
                )
            await session.commit()

            _decision, audit = await agent.evaluate(tx, session)
            await session.refresh(audit)

        await engine.dispose()
        return audit

    audit = asyncio.run(_run())
    raw = audit.code_executed or ""
    assert "Entity History: " in raw, "system prompt should include Entity History section"
    assert "Consider velocity and previous fraud flags." in raw
    assert "19.25" in raw and "31.5" in raw
    msgs = json.loads(raw)
    system = next(m["content"] for m in msgs if m.get("role") == "system")
    assert "Entity History: " in system
    hist_start = system.index("Entity History: ") + len("Entity History: ")
    hist_end = system.index(". Consider velocity and previous fraud flags.", hist_start)
    history_arr = json.loads(system[hist_start:hist_end])
    assert len(history_arr) == 2
    amounts = sorted(float(x["amount"]) for x in history_arr)
    assert amounts == [19.25, 31.5]


def test_evaluate_find_linked_entities_log_precedes_llm_complete(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Gate: borderline/heuristic graph tool runs (logged) before ``shadow_evaluate_llm_complete``."""

    async def _fake_find_linked_entities(
        entity_id: str,
        _tx: TransactionSchema,
        _driver: object,
    ) -> str:
        return (
            f"find_linked_entities({entity_id}): Shared IP history (ORDERED_FROM_IP) probe OK."
        )

    class _FakeNeo4jDriver:
        async def close(self) -> None:
            return None

    monkeypatch.setenv("SHADOW_GRAPH_TOOL_MODE", "always")
    monkeypatch.setattr(
        "shadow_agent.agent.find_linked_entities",
        _fake_find_linked_entities,
    )
    monkeypatch.setattr(
        "shadow_agent.agent.neo4j_driver_from_env",
        lambda: _FakeNeo4jDriver(),
    )

    tx_id = UUID("dddddddd-dddd-dddd-dddd-dddddddddddd")
    tx = TransactionSchema(
        entity_id=tx_id,
        amount=99.0,
        timestamp=datetime(2026, 3, 1, 0, 0, 0, tzinfo=UTC),
        metadata={"user_id": "u_shadow_tool"},
    )
    stub_payload: dict[str, Any] = {
        "transaction_id": str(tx_id),
        "risk_score": 44.0,
        "is_fraud": False,
        "reasoning": ["graph_tool_context_considered"],
        "confidence_metrics": {"graph_tool": True},
        "ai_reasoning": "Reviewed find_linked_entities shared IP summary; borderline approve.",
    }
    llm = _StubLlmClient(stub_payload)
    agent = ShadowAgent(llm_client=llm)

    async def _run() -> None:
        caplog.set_level(logging.INFO)
        engine = create_async_engine(
            "sqlite+aiosqlite:///:memory:",
            poolclass=StaticPool,
            connect_args={"check_same_thread": False},
        )
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        fac = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
        async with fac() as session:
            await agent.evaluate(tx, session)
        await engine.dispose()

    asyncio.run(_run())

    msgs = [r.message for r in caplog.records]
    tool_idxs = [i for i, m in enumerate(msgs) if "shadow_tool_find_linked_entities " in m]
    assert tool_idxs, "expected shadow_tool_find_linked_entities log line"
    llm_idxs = [i for i, m in enumerate(msgs) if "shadow_evaluate_llm_complete" in m]
    assert llm_idxs, "expected shadow_evaluate_llm_complete log line"
    assert min(tool_idxs) < min(llm_idxs), "graph tool should finalize before LLM completion log"

    sys0 = llm.calls[0][0]["content"]
    assert "find_linked_entities" in sys0
    assert "Shared IP history" in sys0


def test_evaluate_check_review_integrity_surfaces_hardware_overlap_in_prompt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Gate: listing_id triggers review-integrity tool; organic-review question sees hardware overlap in GRAPH CONTEXT."""

    async def _fake_check_review_integrity(listing_id: str, _driver: object) -> dict[str, object]:
        return {
            "listing_id": listing_id,
            "reviewer_count": 5,
            "reviewer_ids": ["u1", "u2", "u3", "u4", "u5"],
            "shared_devices": [{"device_id": "hw-shared", "reviewer_user_ids": ["u1", "u2", "u3", "u4"]}],
            "shared_ips": [],
            "reviewers_sharing_device_or_ip_count": 4,
            "signup_analysis": {"all_reviewers_same_10min_window": True},
            "risk_summary": (
                "High probability of a review ring. 4 out of 5 reviewers share a hardware hash "
                "and were created within a 10-minute burst."
            ),
            "review_ring_likely": True,
        }

    class _FakeNeo4jDriver:
        async def close(self) -> None:
            return None

    monkeypatch.setenv("SHADOW_GRAPH_TOOL_MODE", "off")
    monkeypatch.setattr(
        "shadow_agent.agent.check_review_integrity",
        _fake_check_review_integrity,
    )
    monkeypatch.setattr(
        "shadow_agent.agent.neo4j_driver_from_env",
        lambda: _FakeNeo4jDriver(),
    )

    tx_id = UUID("eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee")
    tx = TransactionSchema(
        entity_id=tx_id,
        amount=12.0,
        timestamp=datetime(2026, 3, 1, 0, 0, 0, tzinfo=UTC),
        metadata={"listing_id": "LST-RING-1", "user_id": "u_cur"},
    )
    stub_payload: dict[str, Any] = {
        "transaction_id": str(tx_id),
        "risk_score": 80.0,
        "is_fraud": True,
        "reasoning": ["review_ring_hardware_overlap"],
        "confidence_metrics": {"review_integrity": True},
        "ai_reasoning": (
            "Listing does not look organic: check_review_integrity shows 4/5 reviewers share hardware."
        ),
    }
    llm = _StubLlmClient(stub_payload)
    agent = ShadowAgent(llm_client=llm)

    async def _run() -> str:
        engine = create_async_engine(
            "sqlite+aiosqlite:///:memory:",
            poolclass=StaticPool,
            connect_args={"check_same_thread": False},
        )
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        fac = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
        async with fac() as session:
            await agent.evaluate(tx, session)
        await engine.dispose()
        return llm.calls[0][0]["content"]

    system = asyncio.run(_run())
    assert "check_review_integrity" in system
    assert "High probability of a review ring" in system
    assert "hardware hash" in system
    assert "review_ring_likely" in system
