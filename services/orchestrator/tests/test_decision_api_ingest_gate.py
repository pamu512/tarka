"""Gate: RULE_EVAL_BACKEND=decision_api uses decision-api evaluate, not Python /v1/evaluate."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import select

_SRC_ORCH = Path(__file__).resolve().parents[1]
_SRC_INGESTOR = Path(__file__).resolve().parents[2] / "ingestor" / "src"
_SRC_SHARED = Path(__file__).resolve().parents[2] / "shared"
_SRC_SERVICES = Path(__file__).resolve().parents[2]
for _p in (_SRC_ORCH, _SRC_INGESTOR, _SRC_SHARED, _SRC_SERVICES):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


class _DummyUpstreamResponse:
    def __init__(self, payload: dict[str, object]) -> None:
        self._payload = payload
        self.status_code = 200
        self.text = "{}"

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, object]:
        return self._payload


class _DecisionApiClient:
    def __init__(self) -> None:
        self.posts: list[tuple[str, dict[str, object] | None]] = []

    async def __aenter__(self) -> _DecisionApiClient:
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    async def post(
        self,
        url: str,
        json: dict[str, object] | None = None,
        **kwargs: object,
    ) -> _DummyUpstreamResponse:
        self.posts.append((url, json))
        if url.endswith("/v1/decisions/evaluate"):
            return _DummyUpstreamResponse(
                {
                    "trace_id": "cccccccc-cccc-cccc-cccc-cccccccccccc",
                    "decision": "allow",
                    "score": 0.12,
                    "tags": [],
                    "rule_hits": [],
                    "recommended_action": None,
                    "inference_context": {"schema_version": "3"},
                },
            )
        if "/v1/evaluate" in url and "/decisions/" not in url:
            raise AssertionError(f"python rule engine must not be called: {url!r}")
        raise AssertionError(f"unexpected post url: {url!r}")


def test_ingest_decision_api_backend_no_python_evaluate(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _run() -> None:
        from ingestor.manifest_schema import TransactionSchema
        from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
        from sqlalchemy.pool import StaticPool

        import tarka_shared.audit_trail  # noqa: F401
        import tarka_shared.engine_rules  # noqa: F401
        import tarka_shared.fraud_rules  # noqa: F401

        import models.cases  # noqa: F401
        import models.decision  # noqa: F401
        import models.outbox  # noqa: F401
        from models.outbox import OUTBOX_EVENT_GRAPH_INGEST, OutboxORM
        from transaction_ingest import execute_transaction_ingest
        from tarka_shared.database.session import Base

        entity_id = "dddddddd-dddd-dddd-dddd-dddddddddddd"
        client = _DecisionApiClient()
        monkeypatch.setattr(
            "transaction_ingest.httpx.AsyncClient",
            lambda *a, **k: client,
        )
        monkeypatch.setattr(
            "transaction_ingest.evaluate_transaction_shadow_matches",
            AsyncMock(return_value=[]),
        )
        monkeypatch.setattr(
            "transaction_ingest.dispatch_shadow_investigate_if_review",
            AsyncMock(return_value=None),
        )

        engine = create_async_engine(
            "sqlite+aiosqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        fac = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
        txn = TransactionSchema.model_validate(
            {
                "entity_id": entity_id,
                "amount": 99.0,
                "timestamp": "2026-07-11T12:00:00+00:00",
                "metadata": {"tenant_id": "tenant-gate", "user_id": "u1"},
            },
        )
        request = MagicMock()
        request.headers = {"X-Tenant-Id": "ignored-because-metadata"}
        request.app.state = SimpleNamespace(
            rule_engine_url="http://rules.test",
            decision_api_url="http://core-api.test/decisions",
            rule_eval_backend="decision_api",
            shadow_analyze_timeout_seconds=30.0,
            shadow_agent_url=None,
            shadow_api_key=None,
            graph_client=None,
            shadow_dispatch_nats=None,
            audit_session_factory=fac,
        )

        out = await execute_transaction_ingest(request=request, transaction=txn)
        assert out["transaction_id"] == entity_id
        assert out["risk_decision"]["actions"] == ["ALLOW"]
        assert len(client.posts) == 1
        url, body = client.posts[0]
        assert url == "http://core-api.test/decisions/v1/decisions/evaluate"
        assert body is not None
        assert body["tenant_id"] == "tenant-gate"
        assert body["event_type"] == "payment"
        assert "rules.test" not in url

        async with fac() as session:
            graph_row = (
                await session.scalars(
                    select(OutboxORM).where(OutboxORM.event_type == OUTBOX_EVENT_GRAPH_INGEST),
                )
            ).one()
            assert graph_row is not None

    asyncio.run(_run())


def test_ingest_decision_api_missing_tenant_422(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _run() -> None:
        from fastapi import HTTPException
        from ingestor.manifest_schema import TransactionSchema

        from transaction_ingest import execute_transaction_ingest

        client = _DecisionApiClient()
        monkeypatch.setattr(
            "transaction_ingest.httpx.AsyncClient",
            lambda *a, **k: client,
        )

        txn = TransactionSchema.model_validate(
            {
                "entity_id": "eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee",
                "amount": 1.0,
                "timestamp": "2026-07-11T12:00:00+00:00",
                "metadata": {},
            },
        )
        request = MagicMock()
        request.headers = {}
        request.app.state = SimpleNamespace(
            rule_engine_url="http://rules.test",
            decision_api_url="http://core-api.test/decisions",
            rule_eval_backend="decision_api",
            shadow_analyze_timeout_seconds=30.0,
            shadow_agent_url=None,
            shadow_api_key=None,
            graph_client=None,
            shadow_dispatch_nats=None,
            audit_session_factory=None,
        )

        with pytest.raises(HTTPException) as ei:
            await execute_transaction_ingest(request=request, transaction=txn)
        assert ei.value.status_code == 422
        assert ei.value.detail["error"] == "tenant_id_required"
        assert client.posts == []

    asyncio.run(_run())


def test_create_app_decision_api_without_url_does_not_fall_back_to_python(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """High #3: explicit decision_api without DECISION_API_URL stays decision_api (fail closed)."""
    monkeypatch.delenv("DECISION_API_URL", raising=False)
    from main import create_app

    app = create_app(
        rule_engine_url="http://rules.test",
        shadow_agent_url=None,
        rule_eval_backend="decision_api",
        decision_api_url=None,
    )
    assert app.state.rule_eval_backend == "decision_api"
    assert app.state.decision_api_url is None
