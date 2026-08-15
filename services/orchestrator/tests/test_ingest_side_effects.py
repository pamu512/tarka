"""Internal ingest side-effects route + event outbox commit."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select
from starlette.testclient import TestClient

_SRC_ORCH = Path(__file__).resolve().parents[1]
_SRC_INGESTOR = Path(__file__).resolve().parents[2] / "ingestor" / "src"
_SRC_SHARED = Path(__file__).resolve().parents[2] / "shared"
_SRC_SERVICES = Path(__file__).resolve().parents[2]
for _p in (_SRC_ORCH, _SRC_INGESTOR, _SRC_SHARED, _SRC_SERVICES):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


def test_require_internal_secret_rejects_mismatch(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ORCHESTRATOR_INTERNAL_SECRET", "expected")
    from fastapi import HTTPException
    from ingest_side_effects import require_internal_ingest_auth
    from starlette.requests import Request

    scope = {
        "type": "http",
        "headers": [(b"x-internal-secret", b"expectxx")],
        "method": "POST",
        "path": "/",
    }
    with pytest.raises(HTTPException) as ei:
        require_internal_ingest_auth(Request(scope))
    assert ei.value.status_code == 401


def test_internal_route_commits_outbox(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _run() -> None:
        import models.cases  # noqa: F401
        import models.decision  # noqa: F401
        import models.outbox  # noqa: F401
        import tarka_shared.audit_trail  # noqa: F401
        import tarka_shared.engine_rules  # noqa: F401
        import tarka_shared.fraud_rules  # noqa: F401
        from ingest_side_effects import commit_evaluate_side_effects
        from models.outbox import (
            OUTBOX_EVENT_GRAPH_INGEST,
            OUTBOX_EVENT_VELOCITY_UPDATE,
            OutboxORM,
        )
        from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
        from sqlalchemy.pool import StaticPool
        from tarka_shared.database.session import Base

        engine = create_async_engine(
            "sqlite+aiosqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        fac = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
        event = {
            "tenant_id": "acme",
            "entity_id": "user-9",
            "event_type": "payment",
            "payload": {"amount": 10.0, "timestamp": "2026-08-15T00:00:00+00:00"},
            "metadata": {"ip": "1.1.1.1"},
        }
        audit_id = await commit_evaluate_side_effects(
            fac,
            event=event,
            rule_data={"decision": "allow", "transaction_id": "user-9", "actions": ["ALLOW"]},
            actions=["ALLOW"],
        )
        assert audit_id > 0
        async with fac() as session:
            graph = (
                await session.scalars(
                    select(OutboxORM).where(OutboxORM.event_type == OUTBOX_EVENT_GRAPH_INGEST),
                )
            ).one()
            vel = (
                await session.scalars(
                    select(OutboxORM).where(OutboxORM.event_type == OUTBOX_EVENT_VELOCITY_UPDATE),
                )
            ).one()
        assert graph.payload["event"]["tenant_id"] == "acme"
        assert graph.payload["event"]["entity_id"] == "user-9"
        assert vel.payload["amount_cents"] == 1000
        await engine.dispose()

    asyncio.run(_run())


def test_internal_route_uses_internal_auth(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ORCHESTRATOR_INTERNAL_SECRET", "s3")
    monkeypatch.setenv("ORCHESTRATOR_V1_RATE_LIMIT_RPM", "0")
    from main import create_app

    app = create_app(rule_engine_url="http://rules.test", shadow_agent_url=None)
    monkeypatch.setattr(
        "ingest_side_effects.commit_evaluate_side_effects",
        AsyncMock(return_value=11),
    )
    with TestClient(app) as client:
        denied = client.post(
            "/v1/internal/ingest-side-effects",
            json={
                "event": {"entity_id": "e1", "tenant_id": "t", "event_type": "login"},
                "rule_data": {},
                "actions": ["ALLOW"],
            },
        )
        assert denied.status_code == 401
        ok = client.post(
            "/v1/internal/ingest-side-effects",
            json={
                "event": {"entity_id": "e1", "tenant_id": "t", "event_type": "login"},
                "rule_data": {},
                "actions": ["ALLOW"],
            },
            headers={"x-internal-secret": "s3"},
        )
        assert ok.status_code == 200, ok.text
        assert ok.json()["audit_log_id"] == 11
