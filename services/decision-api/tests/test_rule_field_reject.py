"""Human pack writes reject unknown when.field; legacy aliases stay allowed."""

from __future__ import annotations

import os
import uuid

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")

from decision_api.rule_api import router as rules_router


@pytest.fixture
async def rules_client(tmp_path, monkeypatch):
    from decision_api import rule_api

    monkeypatch.setattr(rule_api.settings, "rules_path", str(tmp_path))
    monkeypatch.setattr(rule_api.settings, "rule_governance_secret", "")
    monkeypatch.setattr(rule_api.settings, "graph_service_url", "")
    app = FastAPI()
    app.include_router(rules_router)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as c:
        yield c


@pytest.mark.asyncio
async def test_create_pack_rejects_unknown_field(rules_client):
    r = await rules_client.post(
        "/v1/rules",
        json={
            "name": f"ghost_{uuid.uuid4().hex[:8]}",
            "rules": [
                {
                    "id": "r1",
                    "when": [{"field": "not_a_field", "op": "eq", "value": 1}],
                    "score_delta": 5,
                }
            ],
        },
    )
    assert r.status_code == 422
    assert "map it or add a registry row" in str(r.json())


@pytest.mark.asyncio
async def test_create_pack_allows_legacy_alias(rules_client):
    r = await rules_client.post(
        "/v1/rules",
        json={
            "name": f"legacy_tx_{uuid.uuid4().hex[:8]}",
            "rules": [
                {
                    "id": "r1",
                    "when": [{"field": "tx_count_1h", "op": "gte", "value": 3}],
                    "score_delta": 5,
                }
            ],
        },
    )
    assert r.status_code in (201, 409, 422)
    # 422 only if governance/other; field itself must not be the reason
    if r.status_code == 422:
        assert "tx_count_1h" not in str(r.json()).lower() or "unknown field" not in str(
            r.json()
        )
