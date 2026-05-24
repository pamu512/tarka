"""Gate: execute_transaction_ingest enqueues outbox tasks inside atomic_transaction."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from sqlalchemy import select

_SRC_ORCH = Path(__file__).resolve().parents[1] / "src"
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


class _EvalOnlyAsyncClient:
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
            return _DummyUpstreamResponse(
                {
                    "actions": ["ALLOW"],
                    "transaction_id": "tid",
                    "evaluation_trace": [
                        {
                            "rule_id": "11111111-1111-1111-1111-111111111111",
                            "rule_name": "demo_allow",
                            "priority": 10,
                            "matched": True,
                            "action": "ALLOW",
                        },
                    ],
                    "blocking_rule_id": None,
                },
            )
        raise AssertionError(f"unexpected post url: {url!r}")


def test_execute_transaction_ingest_writes_outbox_tasks(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _run() -> None:
        from ingestor.manifest_schema import TransactionSchema
        from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
        from sqlalchemy.pool import StaticPool

        import tarka_shared.audit_trail  # noqa: F401
        import tarka_shared.engine_rules  # noqa: F401
        import tarka_shared.fraud_rules  # noqa: F401

        import orchestrator.models.cases  # noqa: F401
        import orchestrator.models.decision  # noqa: F401
        import orchestrator.models.outbox  # noqa: F401
        from orchestrator.anumana_velocity import device_hash_token
        from orchestrator.models.outbox import (
            OUTBOX_EVENT_GRAPH_INGEST,
            OUTBOX_EVENT_VELOCITY_UPDATE,
            OutboxORM,
        )
        from orchestrator.transaction_ingest import execute_transaction_ingest
        from tarka_shared.database.session import Base

        entity_id = "33333333-3333-3333-3333-333333333333"

        class _EvalClient(_EvalOnlyAsyncClient):
            async def post(
                self,
                url: str,
                json: dict[str, object] | None = None,
                **kwargs: object,
            ) -> _DummyUpstreamResponse:
                if "/v1/evaluate" in url:
                    return _DummyUpstreamResponse(
                        {
                            "actions": ["ALLOW"],
                            "transaction_id": entity_id,
                            "evaluation_trace": [
                                {
                                    "rule_id": "11111111-1111-1111-1111-111111111111",
                                    "rule_name": "demo_allow",
                                    "priority": 10,
                                    "matched": True,
                                    "action": "ALLOW",
                                },
                            ],
                            "blocking_rule_id": None,
                        },
                    )
                raise AssertionError(f"unexpected post url: {url!r}")

        monkeypatch.setattr(
            "orchestrator.transaction_ingest.httpx.AsyncClient",
            lambda *a, **k: _EvalClient(),
        )
        monkeypatch.setattr(
            "orchestrator.transaction_ingest.evaluate_transaction_shadow_matches",
            AsyncMock(return_value=[]),
        )
        monkeypatch.setattr(
            "orchestrator.transaction_ingest.dispatch_shadow_investigate_if_review",
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
                "amount": 12.5,
                "timestamp": "2026-05-09T12:00:00+00:00",
                "metadata": {
                    "user_id": "u1",
                    "canvas_fingerprint": "ab" * 32,
                    "ip": "10.0.0.1",
                    "tenant_id": "tenant-a",
                    "device_session_id": "sess-1",
                },
            },
        )
        request = MagicMock()
        request.app.state = SimpleNamespace(
            rule_engine_url="http://rules.test",
            shadow_analyze_timeout_seconds=30.0,
            shadow_agent_url=None,
            shadow_api_key=None,
            graph_client=None,
            shadow_dispatch_nats=None,
            audit_session_factory=fac,
        )

        out = await execute_transaction_ingest(request=request, transaction=txn)
        assert out["transaction_id"] == entity_id

        async with fac() as session:
            graph_row = (
                await session.scalars(
                    select(OutboxORM).where(OutboxORM.event_type == OUTBOX_EVENT_GRAPH_INGEST),
                )
            ).one()
            vel_rows = (
                await session.scalars(
                    select(OutboxORM).where(OutboxORM.event_type == OUTBOX_EVENT_VELOCITY_UPDATE),
                )
            ).all()
        assert graph_row.idempotency_key.startswith(f"graph_ingest:{entity_id}:")
        assert graph_row.payload["transaction_id"] == entity_id
        assert graph_row.payload["entity_id"] == entity_id
        assert graph_row.payload["blocking_rule_id"] is None
        assert "11111111-1111-1111-1111-111111111111" in graph_row.payload["resolved_rules"]
        assert graph_row.payload["edge_transaction_payload_envelope"]["entity_id"] == entity_id
        assert len(vel_rows) == 1
        vel_row = vel_rows[0]
        assert vel_row.idempotency_key.startswith(f"velocity_update:{entity_id}:")
        assert vel_row.payload["entity_id"] == entity_id
        assert vel_row.payload["amount_cents"] == 1250
        assert vel_row.payload["transaction_timestamp_utc"] == "2026-05-09T12:00:00+00:00"
        assert vel_row.payload["device_hash_string"] == device_hash_token("ab" * 32)
        assert vel_row.payload["client_browser_metadata_context"]["canvas_fingerprint"] == "ab" * 32
        assert vel_row.payload["client_browser_metadata_context"]["ip"] == "10.0.0.1"
        assert vel_row.payload["client_browser_metadata_context"]["tenant_id"] == "tenant-a"
        await engine.dispose()

    asyncio.run(_run())
