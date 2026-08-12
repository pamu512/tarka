"""GET /v1/calibration/shadow-promote-gate contract (Fraud Ops 4.2 + P0-CC)."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from decision_api.calibration_api import router as calibration_router
from decision_api.db import get_session


class _EmptyResult:
    def scalars(self):
        return self

    def all(self):
        return []


class _EmptySession:
    async def execute(self, *a, **k):
        return _EmptyResult()


@pytest.fixture
async def challenge_client(monkeypatch):
    monkeypatch.setenv("ALLOW_INSECURE_NO_AUTH", "true")

    from auth_rbac import AuthUser

    app = FastAPI()

    @app.middleware("http")
    async def _inject_auth(request, call_next):
        request.state.auth_user = AuthUser(
            "test-analyst", ["analyst", "admin"], "test", tenant_ids={"*"}
        )
        return await call_next(request)

    app.include_router(calibration_router)

    async def _session_override():
        yield _EmptySession()

    app.dependency_overrides[get_session] = _session_override

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_shadow_promote_gate_endpoint(challenge_client):
    r = await challenge_client.get("/v1/calibration/shadow-promote-gate")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["schema_id"] == "tarka.shadow_promote_gate/v1"
    assert body["blocked"]["promote_allowed"] is False
    assert body["allowed"]["promote_allowed"] is True
    assert "shadow_vs_primary_diff_recipe.sql" in body["recipe_path"]
    assert body["label_gated_promote"]["promote_allowed"] is False
    assert body["mcnemar_promote_gate"]["promote_allowed"] is False
    assert "drift_promote_gate" in body
    assert body["desk_promote_gate"]["promote_allowed"] is False
    assert "drift_promote_gate" in (body["desk_promote_gate"].get("requires") or [])
    assert "champion_challenger" in body
    assert (
        body["champion_challenger"]["schema_id"] == "tarka.champion_challenger_audit/v1"
    )
