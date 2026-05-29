"""Gate: POST /v1/operational-signals idempotency + atomic persistence."""

from __future__ import annotations

import asyncio
import sys
import uuid
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import func, select
from starlette.testclient import TestClient

_SRC_ORCH = Path(__file__).resolve().parents[1] / "src"
_SRC_INGESTOR = Path(__file__).resolve().parents[2] / "ingestor" / "src"
_SRC_SHARED = Path(__file__).resolve().parents[2] / "shared"
_SRC_SERVICES = Path(__file__).resolve().parents[2]
for _p in (_SRC_ORCH, _SRC_INGESTOR, _SRC_SHARED, _SRC_SERVICES):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

_ENTITY_ID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
_AUTH_HEADERS = {"X-Auth-Token": "gate-operational-signals-token"}


def _chargeback_body(*, idempotency_key: str = "cb:entity-1:4853") -> dict:
    return {
        "idempotency_key": idempotency_key,
        "target_entity_id": _ENTITY_ID,
        "signal_type": "CHARGEBACK_RECEIVED",
        "metadata": {
            "amount_cents": 1250,
            "currency": "USD",
            "chargeback_reason_code": "4853",
            "card_network": "VISA",
        },
    }


def test_post_operational_signal_returns_202_and_persists_row(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ORCHESTRATOR_V1_RATE_LIMIT_RPM", "0")
    import orchestrator.models.operational_signals  # noqa: F401, PLC0415
    import orchestrator.models.outbox  # noqa: F401, PLC0415

    from orchestrator.main import create_app  # noqa: E402
    from orchestrator.models.operational_signals import OperationalSignalORM  # noqa: E402
    from orchestrator.models.outbox import OUTBOX_EVENT_SHADOW_RETRO_TAG, OutboxORM  # noqa: E402

    redis = AsyncMock()
    redis.set = AsyncMock(return_value=True)
    redis.delete = AsyncMock(return_value=1)
    redis.ping = AsyncMock(return_value=True)

    app = create_app(
        rule_engine_url="http://rules.test",
        shadow_agent_url=None,
        audit_database_url="sqlite+aiosqlite:///:memory:",
        anumana_redis_client=redis,
    )

    with TestClient(app) as client:
        r = client.post("/v1/operational-signals", json=_chargeback_body(), headers=_AUTH_HEADERS)
        assert r.status_code == 202, r.text
        data = r.json()
        assert data["status"] == "ACCEPTED"
        event_id = data["event_id"]
        uuid.UUID(event_id)

        redis.set.assert_awaited()
        lock_key = redis.set.await_args.args[0]
        assert lock_key.startswith("tarka:operational_signal:idempotency:")

        async def _count_rows() -> int:
            fac = app.state.audit_session_factory
            assert fac is not None
            async with fac() as session:
                return int(
                    await session.scalar(select(func.count()).select_from(OperationalSignalORM))
                )

        assert asyncio.run(_count_rows()) == 1

        async def _fetch_outbox() -> OutboxORM | None:
            fac = app.state.audit_session_factory
            assert fac is not None
            async with fac() as session:
                return await session.scalar(
                    select(OutboxORM).where(OutboxORM.event_type == OUTBOX_EVENT_SHADOW_RETRO_TAG),
                )

        outbox_row = asyncio.run(_fetch_outbox())
        assert outbox_row is not None
        assert (
            outbox_row.idempotency_key == f"shadow_tag_ops:{_chargeback_body()['idempotency_key']}"
        )
        assert outbox_row.payload["entity_id"] == _ENTITY_ID
        assert outbox_row.payload["signal_id"] == event_id
        assert outbox_row.payload["metadata"]["chargeback_reason_code"] == "4853"


def test_post_operational_signal_replays_idempotent_202(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ORCHESTRATOR_V1_RATE_LIMIT_RPM", "0")
    import orchestrator.models.operational_signals  # noqa: F401, PLC0415

    from orchestrator.main import create_app  # noqa: E402

    redis = AsyncMock()
    redis.set = AsyncMock(side_effect=[True, None])
    redis.delete = AsyncMock(return_value=1)
    redis.ping = AsyncMock(return_value=True)

    app = create_app(
        rule_engine_url="http://rules.test",
        shadow_agent_url=None,
        audit_database_url="sqlite+aiosqlite:///:memory:",
        anumana_redis_client=redis,
    )

    body = _chargeback_body(idempotency_key="cb:replay:1")

    with TestClient(app) as client:
        first = client.post("/v1/operational-signals", json=body, headers=_AUTH_HEADERS)
        assert first.status_code == 202, first.text
        first_id = first.json()["event_id"]

        second = client.post("/v1/operational-signals", json=body, headers=_AUTH_HEADERS)
        assert second.status_code == 202, second.text
        assert second.json()["event_id"] == first_id


def test_post_operational_signal_requires_redis(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ORCHESTRATOR_V1_RATE_LIMIT_RPM", "0")
    import orchestrator.models.operational_signals  # noqa: F401, PLC0415

    from orchestrator.main import create_app  # noqa: E402

    app = create_app(
        rule_engine_url="http://rules.test",
        shadow_agent_url=None,
        audit_database_url="sqlite+aiosqlite:///:memory:",
        anumana_redis_client=None,
    )

    with TestClient(app) as client:
        r = client.post("/v1/operational-signals", json=_chargeback_body(), headers=_AUTH_HEADERS)
        assert r.status_code == 503


def test_post_operational_signal_rejects_invalid_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ORCHESTRATOR_V1_RATE_LIMIT_RPM", "0")
    import orchestrator.models.operational_signals  # noqa: F401, PLC0415

    from orchestrator.main import create_app  # noqa: E402

    redis = AsyncMock()
    redis.set = AsyncMock(return_value=True)
    redis.ping = AsyncMock(return_value=True)

    app = create_app(
        rule_engine_url="http://rules.test",
        shadow_agent_url=None,
        audit_database_url="sqlite+aiosqlite:///:memory:",
        anumana_redis_client=redis,
    )

    with TestClient(app) as client:
        r = client.post(
            "/v1/operational-signals",
            json={
                "idempotency_key": "cb:bad",
                "target_entity_id": _ENTITY_ID,
                "signal_type": "REFUND_ISSUED",
                "metadata": {
                    "amount_cents": 100,
                    "currency": "USD",
                    "chargeback_reason_code": "4853",
                    "card_network": "VISA",
                },
            },
            headers=_AUTH_HEADERS,
        )
        assert r.status_code == 422
