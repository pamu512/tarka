"""Gate: Lekh ``decisions`` rows store evaluation trace; every BLOCK pins the exact ``blocking_rule_id``."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import httpx
import pytest
from sqlalchemy import select
from starlette.testclient import TestClient

_SRC_ORCH = Path(__file__).resolve().parents[1] / "src"
_SRC_INGESTOR = Path(__file__).resolve().parents[2] / "ingestor" / "src"
_SRC_SHARED = Path(__file__).resolve().parents[2] / "shared"
for _p in (_SRC_ORCH, _SRC_INGESTOR, _SRC_SHARED):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


class _DummyUpstreamResponse:
    def __init__(self, payload: dict[str, object]) -> None:
        self._payload = payload
        self.status_code = 200
        self.text = json.dumps(payload)

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, object]:
        return self._payload


class _EvalOnlyAsyncClient:
    def __init__(self, evaluate_json: dict[str, object]) -> None:
        self._evaluate_json = evaluate_json

    async def __aenter__(self) -> _EvalOnlyAsyncClient:
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    async def post(
        self,
        url: str,
        json: dict[str, object] | None = None,
        **kwargs: object,
    ) -> _DummyUpstreamResponse:
        if "/v1/evaluate" in url:
            return _DummyUpstreamResponse(self._evaluate_json)
        raise AssertionError(f"unexpected post url: {url!r}")


def test_persist_lekh_decision_block_requires_blocking_rule_id() -> None:
    import orchestrator.models.decision  # noqa: F401, PLC0415
    import orchestrator.models.cases  # noqa: F401, PLC0415
    import tarka_shared.audit_trail  # noqa: F401, PLC0415
    import tarka_shared.engine_rules  # noqa: F401, PLC0415
    import tarka_shared.fraud_rules  # noqa: F401, PLC0415

    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
    from sqlalchemy.pool import StaticPool
    from tarka_shared.database.session import Base

    from orchestrator.enforcement.log_decision import persist_lekh_decision

    async def _run() -> None:
        engine = create_async_engine(
            "sqlite+aiosqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        fac = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        async with fac() as session:
            with pytest.raises(ValueError, match="blocking_rule_id"):
                async with session.begin():
                    await persist_lekh_decision(
                        session,
                        entity_id="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
                        rule_data={"actions": ["BLOCK"], "evaluation_trace": []},
                    )

        await engine.dispose()

    asyncio.run(_run())


def test_v1_ingest_block_writes_decision_row_with_exact_rule_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import orchestrator.models.cases  # noqa: F401, PLC0415
    import orchestrator.models.decision  # noqa: F401, PLC0415
    import tarka_shared.audit_trail  # noqa: F401, PLC0415
    import tarka_shared.engine_rules  # noqa: F401, PLC0415
    import tarka_shared.fraud_rules  # noqa: F401, PLC0415

    from orchestrator.main import create_app
    from orchestrator.models.decision import DecisionORM

    rule_id = "00000000-0000-0000-0000-00000000c0de"
    txn = "99999999-9999-9999-9999-999999999999"
    evaluate_json: dict[str, object] = {
        "actions": ["BLOCK"],
        "transaction_id": txn,
        "evaluation_trace": [
            {
                "rule_id": rule_id,
                "rule_name": "demo_stress_block_lane",
                "priority": 5,
                "matched": True,
                "action": "BLOCK",
            },
        ],
        "blocking_rule_id": rule_id,
    }

    monkeypatch.setattr(
        "orchestrator.transaction_ingest.httpx.AsyncClient",
        lambda *a, **k: _EvalOnlyAsyncClient(evaluate_json),
    )

    app = create_app(
        rule_engine_url="http://rules.test",
        shadow_agent_url=None,
        audit_database_url="sqlite+aiosqlite:///:memory:",
    )

    body = {
        "entity_id": txn,
        "amount": 1.0,
        "timestamp": "2026-05-09T12:00:00+00:00",
        "metadata": {"lane": "STRESS_BLOCK_LANE"},
    }

    async def _check() -> None:
        fac = app.state.audit_session_factory
        assert fac is not None
        async with fac() as session:
            rows = (await session.scalars(select(DecisionORM))).all()
        assert len(rows) == 1
        row = rows[0]
        assert row.entity_id == txn
        assert row.blocking_rule_id == rule_id
        assert row.final_decision == "BLOCK"
        assert row.actions_json == ["BLOCK"]
        assert len(row.execution_trace_json) == 1
        assert row.execution_trace_json[0]["rule_id"] == rule_id
        assert row.raw_rule_engine_json["blocking_rule_id"] == rule_id

    with TestClient(app) as client:
        r = client.post("/v1/ingest", json=body)
        assert r.status_code == 200, r.text
        asyncio.run(_check())
