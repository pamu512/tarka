"""Gate: shared /v1 auth + rate-limit dependencies."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from starlette.testclient import TestClient

_SRC_ORCH = Path(__file__).resolve().parents[1]
_SRC_INGESTOR = Path(__file__).resolve().parents[2] / "ingestor" / "src"
_SRC_SHARED = Path(__file__).resolve().parents[2] / "shared"
_SRC_SERVICES = Path(__file__).resolve().parents[2]
for _p in (_SRC_ORCH, _SRC_INGESTOR, _SRC_SHARED, _SRC_SERVICES):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

_ENTITY_ID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"


def _signal_body(*, idempotency_key: str = "cb:auth-gate:1") -> dict:
    return {
        "idempotency_key": idempotency_key,
        "target_entity_id": _ENTITY_ID,
        "signal_type": "CHARGEBACK_RECEIVED",
        "metadata": {
            "amount_cents": 500,
            "currency": "USD",
            "chargeback_reason_code": "4853",
            "card_network": "VISA",
        },
    }


def test_operational_signals_requires_auth_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ORCHESTRATOR_V1_RATE_LIMIT_RPM", "0")
    import models.operational_signals  # noqa: F401, PLC0415

    from main import create_app  # noqa: E402

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
        r = client.post("/v1/operational-signals", json=_signal_body())
        assert r.status_code == 422


def test_operational_signals_rejects_invalid_auth_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ORCHESTRATOR_V1_RATE_LIMIT_RPM", "0")
    monkeypatch.setenv("ORCHESTRATOR_V1_AUTH_TOKEN", "expected-secret")
    import models.operational_signals  # noqa: F401, PLC0415

    from main import create_app  # noqa: E402

    redis = AsyncMock()
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
            json=_signal_body(idempotency_key="cb:auth-gate:2"),
            headers={"X-Auth-Token": "wrong-token"},
        )
        assert r.status_code == 401
        assert r.json()["detail"]["error"] == "unauthorized"


def test_operational_signals_rate_limited(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ORCHESTRATOR_V1_RATE_LIMIT_RPM", "1")
    import models.operational_signals  # noqa: F401, PLC0415

    from main import create_app  # noqa: E402

    redis = AsyncMock()
    redis.set = AsyncMock(return_value=True)
    redis.ping = AsyncMock(return_value=True)

    app = create_app(
        rule_engine_url="http://rules.test",
        shadow_agent_url=None,
        audit_database_url="sqlite+aiosqlite:///:memory:",
        anumana_redis_client=redis,
    )

    headers = {"X-Auth-Token": "rate-limit-gate-token"}

    with TestClient(app) as client:
        first = client.post(
            "/v1/operational-signals",
            json=_signal_body(idempotency_key="cb:rate-gate:1"),
            headers=headers,
        )
        assert first.status_code == 202, first.text

        second = client.post(
            "/v1/operational-signals",
            json=_signal_body(idempotency_key="cb:rate-gate:2"),
            headers=headers,
        )
        assert second.status_code == 429
        assert second.json()["detail"]["error"] == "rate_limit_exceeded"
