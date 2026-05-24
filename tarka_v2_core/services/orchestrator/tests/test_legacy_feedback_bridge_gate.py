"""Gate: deprecated legacy feedback routes bridge to operational-signals ingress."""

from __future__ import annotations

import asyncio
import sys
import uuid
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select
from starlette.testclient import TestClient

_SRC_ORCH = Path(__file__).resolve().parents[1] / "src"
_SRC_INGESTOR = Path(__file__).resolve().parents[2] / "ingestor" / "src"
_SRC_SHARED = Path(__file__).resolve().parents[2] / "shared"
_SRC_SERVICES = Path(__file__).resolve().parents[2]
for _p in (_SRC_ORCH, _SRC_INGESTOR, _SRC_SHARED, _SRC_SERVICES):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

_ENTITY_ID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"


def _redis_mock(*, lock_ok: bool = True) -> AsyncMock:
    redis = AsyncMock()
    redis.set = AsyncMock(return_value=lock_ok)
    redis.delete = AsyncMock(return_value=1)
    redis.ping = AsyncMock(return_value=True)
    return redis


def test_legacy_ai_feedback_bridges_to_operational_signals(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ORCHESTRATOR_V1_RATE_LIMIT_RPM", "0")
    import orchestrator.models.operational_signals  # noqa: F401, PLC0415

    from orchestrator.main import create_app  # noqa: E402
    from orchestrator.models.operational_signals import OperationalSignalORM  # noqa: E402

    app = create_app(
        rule_engine_url="http://rules.test",
        shadow_agent_url=None,
        audit_database_url="sqlite+aiosqlite:///:memory:",
        anumana_redis_client=_redis_mock(),
    )

    payload = {
        "rejection_reasons": ["Hallucinated merchant name"],
        "tenant_id": "demo",
        "trace_id": "tr-gate-001",
        "entity_id": _ENTITY_ID,
        "source": "pytest",
        "context": "Analyst rejected Shadow narrative.",
    }
    with TestClient(app) as client:
        r = client.post("/v1/ai/feedback", json=payload)
    assert r.status_code == 202, r.text
    body = r.json()
    assert body["ok"] is True
    assert body["deprecated"] is True
    assert body["successor"] == "/v1/operational-signals"
    assert body["event_id"] == body["feedback_id"]
    assert r.headers.get("Deprecation") == "true"
    assert "operational-signals" in (r.headers.get("Link") or "")

    async def _count_rows() -> int:
        fac = app.state.audit_session_factory
        assert fac is not None
        async with fac() as session:
            return len((await session.scalars(select(OperationalSignalORM))).all())

    assert asyncio.run(_count_rows()) == 1


def test_legacy_consortium_feedback_bridges_to_operational_signals(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ORCHESTRATOR_V1_RATE_LIMIT_RPM", "0")
    import orchestrator.models.operational_signals  # noqa: F401, PLC0415

    from orchestrator.main import create_app  # noqa: E402
    from orchestrator.models.operational_signals import OperationalSignalORM  # noqa: E402

    app = create_app(
        rule_engine_url="http://rules.test",
        shadow_agent_url=None,
        audit_database_url="sqlite+aiosqlite:///:memory:",
        anumana_redis_client=_redis_mock(),
    )

    with TestClient(app) as client:
        r = client.post(
            "/v1/consortium/feedback",
            json={
                "tenant_id": "tenant-a",
                "entity_id": "entity-legacy-1",
                "outcome": "confirmed_fraud",
            },
        )
    assert r.status_code == 202, r.text
    body = r.json()
    assert body["ok"] is True
    assert body["signal_hash"]
    assert body["event_id"]

    async def _fetch_row() -> OperationalSignalORM:
        fac = app.state.audit_session_factory
        assert fac is not None
        async with fac() as session:
            row = (await session.scalars(select(OperationalSignalORM))).first()
        assert row is not None
        return row

    row = asyncio.run(_fetch_row())
    assert row.signal_type == "MANUAL_OVERRIDE"
    assert row.metadata_json["reason_code"] == "CONFIRMED_FRAUD"


def test_legacy_copilot_feedback_bridges_to_operational_signals(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ORCHESTRATOR_V1_RATE_LIMIT_RPM", "0")
    import orchestrator.models.operational_signals  # noqa: F401, PLC0415

    from orchestrator.main import create_app  # noqa: E402

    app = create_app(
        rule_engine_url="http://rules.test",
        shadow_agent_url=None,
        audit_database_url="sqlite+aiosqlite:///:memory:",
        anumana_redis_client=_redis_mock(),
    )

    with TestClient(app) as client:
        r = client.post(
            "/v1/feedback",
            json={
                "turn_id": "turn-abc",
                "rating": -1,
                "note": "Wrong merchant",
                "tenant_id": "tenant-a",
                "analyst_id": "analyst-7",
            },
        )
    assert r.status_code == 202, r.text
    body = r.json()
    assert body["stored"] is True
    assert body["feedback_id"] == body["event_id"]
    uuid.UUID(body["event_id"])


def test_legacy_ai_feedback_transform_unit() -> None:
    from orchestrator.openapi_schemas import AiFeedbackRequest
    from orchestrator.routes.legacy_feedback_bridge import ai_feedback_to_operational_signal
    from orchestrator.schemas.operational_signals import SignalType

    body = AiFeedbackRequest.model_validate(
        {
            "rejection_reasons": ["bad output"],
            "entity_id": _ENTITY_ID,
            "source": "shadow_llm",
        },
    )
    mapped = ai_feedback_to_operational_signal(body)
    assert mapped.signal_type == SignalType.MANUAL_OVERRIDE
    assert str(mapped.target_entity_id) == _ENTITY_ID
    assert mapped.metadata.reason_code == "AI_REJECTION"
