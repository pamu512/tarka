"""Contract gate: HIL override POST/GET round-trip + operational_signals audit (no browser)."""

from __future__ import annotations

import asyncio
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock
from uuid import UUID

import pytest
from sqlalchemy import select
from starlette.testclient import TestClient

_SRC_ORCH = Path(__file__).resolve().parents[1]
_SRC_INGESTOR = Path(__file__).resolve().parents[2] / "ingestor" / "src"
_SRC_SHARED = Path(__file__).resolve().parents[2] / "shared"
for _p in (_SRC_ORCH, _SRC_INGESTOR, _SRC_SHARED):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

_ENTITY_ID = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
_TENANT = "tenant-contract-gate"


@pytest.fixture()
def hil_client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("ORCHESTRATOR_V1_RATE_LIMIT_RPM", "0")
    import models.operational_signals  # noqa: F401, PLC0415
    import models.outbox  # noqa: F401, PLC0415
    import tarka_shared.audit_trail  # noqa: F401, PLC0415

    from analytics.hil_context_store import InMemoryHilContextOverrideStore
    from main import create_app  # noqa: E402

    redis = AsyncMock()
    _locked: set[str] = set()

    async def _redis_set(key: str, value: object, nx: bool = False, ex: int | None = None) -> bool:
        if nx:
            if key in _locked:
                return False
            _locked.add(key)
            return True
        return True

    redis.set = AsyncMock(side_effect=_redis_set)
    redis.ping = AsyncMock(return_value=True)

    app = create_app(
        rule_engine_url="http://rules.test",
        shadow_agent_url=None,
        audit_database_url="sqlite+aiosqlite:///:memory:",
        anumana_redis_client=redis,
        hil_context_override_store_override=InMemoryHilContextOverrideStore(),
    )
    with TestClient(app) as client:
        yield client


def test_hil_override_round_trip_and_operational_signal_audit(hil_client: TestClient) -> None:
    from models.operational_signals import OperationalSignalORM
    from schemas.operational_signals import SignalType

    expiry = (datetime.now(tz=UTC) + timedelta(days=30)).isoformat()
    body = {
        "idempotency_key": "hil:contract:roundtrip:1",
        "tenant_id": _TENANT,
        "override_type": "ALLOW_SEASONAL_SPIKE",
        "scope_key": "day_of_year:172",
        "expires_at": expiry,
        "analyst_rationale": "Seasonal promo spike approved for Prime Day window.",
        "analyst_id": "analyst.contract.gate",
    }

    post = hil_client.post(
        f"/v1/entities/{_ENTITY_ID}/hil-overrides",
        json=body,
        headers={"X-Auth-Token": "contract-gate-token"},
    )
    assert post.status_code == 202, post.text
    accepted = post.json()
    event_id = accepted["event_id"]
    UUID(event_id)
    assert accepted["override"]["override_type"] == "ALLOW_SEASONAL_SPIKE"
    assert accepted["override"]["scope_key"] == "day_of_year:172"

    dup = hil_client.post(
        f"/v1/entities/{_ENTITY_ID}/hil-overrides",
        json=body,
        headers={"X-Auth-Token": "contract-gate-token"},
    )
    assert dup.status_code == 202, dup.text
    assert dup.json()["event_id"] == event_id

    listed = hil_client.get(
        f"/v1/entities/{_ENTITY_ID}/hil-overrides",
        params={"tenant_id": _TENANT},
        headers={"X-Auth-Token": "contract-gate-token"},
    )
    assert listed.status_code == 200, listed.text
    payload = listed.json()
    assert payload["entity_id"] == _ENTITY_ID
    assert payload["tenant_id"] == _TENANT
    assert len(payload["overrides"]) == 1
    row = payload["overrides"][0]
    assert row["override_type"] == "ALLOW_SEASONAL_SPIKE"
    assert row["scope_key"] == "day_of_year:172"

    async def _assert_signal() -> None:
        fac = hil_client.app.state.audit_session_factory
        assert fac is not None
        async with fac() as session:
            signal = await session.scalar(
                select(OperationalSignalORM).where(
                    OperationalSignalORM.idempotency_key == "hil:contract:roundtrip:1",
                ),
            )
            assert signal is not None
            assert signal.signal_type == SignalType.HIL_CONTEXT_OVERRIDE.value
            assert signal.target_entity_id == _ENTITY_ID
            assert signal.metadata_json.get("analyst_id") == "analyst.contract.gate"

    asyncio.run(_assert_signal())
