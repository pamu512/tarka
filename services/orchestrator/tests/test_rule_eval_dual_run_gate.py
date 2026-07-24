"""Gate: RULE_EVAL_DUAL_RUN calls both engines; side effects from decision-api."""

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


class _DualRunClient:
    def __init__(
        self, *, python_actions: list[str] | None = None, python_fail: bool = False
    ) -> None:
        self.posts: list[str] = []
        self._python_actions = python_actions or ["ALLOW"]
        self._python_fail = python_fail

    async def __aenter__(self) -> _DualRunClient:
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    async def post(
        self,
        url: str,
        json: dict[str, object] | None = None,
        **kwargs: object,
    ) -> _DummyUpstreamResponse:
        self.posts.append(url)
        if url.endswith("/v1/decisions/evaluate"):
            return _DummyUpstreamResponse(
                {
                    "trace_id": "ffffffff-ffff-ffff-ffff-ffffffffffff",
                    "decision": "allow",
                    "score": 0.1,
                    "tags": [],
                    "rule_hits": [],
                    "recommended_action": None,
                    "inference_context": {"schema_version": "3"},
                },
            )
        if url.endswith("/v1/evaluate"):
            if self._python_fail:
                raise ConnectionError("python sidecar down")
            return _DummyUpstreamResponse(
                {
                    "actions": list(self._python_actions),
                    "transaction_id": "tid",
                    "evaluation_trace": [],
                    "blocking_rule_id": None,
                },
            )
        raise AssertionError(f"unexpected post url: {url!r}")


def test_dual_run_calls_both_prefers_decision_api(monkeypatch: pytest.MonkeyPatch) -> None:
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

        entity_id = "11111111-1111-1111-1111-111111111111"
        client = _DualRunClient(python_actions=["FLAG"])
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
                "amount": 10.0,
                "timestamp": "2026-07-12T00:00:00+00:00",
                "metadata": {"tenant_id": "tenant-dual"},
            },
        )
        request = MagicMock()
        request.headers = {}
        request.app.state = SimpleNamespace(
            rule_engine_url="http://rules.test",
            decision_api_url="http://core-api.test/decisions",
            rule_eval_backend="python",  # dual-run still prefers decision-api side effects
            rule_eval_dual_run=True,
            shadow_analyze_timeout_seconds=30.0,
            shadow_agent_url=None,
            shadow_api_key=None,
            graph_client=None,
            shadow_dispatch_nats=None,
            audit_session_factory=fac,
        )

        out = await execute_transaction_ingest(request=request, transaction=txn)
        assert out["risk_decision"]["actions"] == ["ALLOW"]
        assert any(u.endswith("/v1/decisions/evaluate") for u in client.posts)
        assert any(u.endswith("/v1/evaluate") for u in client.posts)

        async with fac() as session:
            assert (
                await session.scalars(
                    select(OutboxORM).where(OutboxORM.event_type == OUTBOX_EVENT_GRAPH_INGEST),
                )
            ).one()

    asyncio.run(_run())


def test_dual_run_python_failure_still_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
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
        from transaction_ingest import execute_transaction_ingest
        from tarka_shared.database.session import Base

        entity_id = "22222222-2222-2222-2222-222222222222"
        client = _DualRunClient(python_fail=True)
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
                "amount": 10.0,
                "timestamp": "2026-07-12T00:00:00+00:00",
                "metadata": {"tenant_id": "tenant-dual"},
            },
        )
        request = MagicMock()
        request.headers = {}
        request.app.state = SimpleNamespace(
            rule_engine_url="http://rules.test",
            decision_api_url="http://core-api.test/decisions",
            rule_eval_backend="decision_api",
            rule_eval_dual_run=True,
            shadow_analyze_timeout_seconds=30.0,
            shadow_agent_url=None,
            shadow_api_key=None,
            graph_client=None,
            shadow_dispatch_nats=None,
            audit_session_factory=fac,
        )

        out = await execute_transaction_ingest(request=request, transaction=txn)
        assert out["risk_decision"]["actions"] == ["ALLOW"]
        assert any(u.endswith("/v1/decisions/evaluate") for u in client.posts)

    asyncio.run(_run())
