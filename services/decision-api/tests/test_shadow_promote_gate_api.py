"""GET /v1/calibration/shadow-promote-gate contract (Fraud Ops 4.2)."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from decision_api.calibration_api import router as calibration_router


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

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


@pytest.mark.asyncio
async def test_shadow_promote_gate_endpoint(challenge_client):
    r = await challenge_client.get("/v1/calibration/shadow-promote-gate")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["schema_id"] == "tarka.shadow_promote_gate/v1"
    assert body["blocked"]["promote_allowed"] is False
    assert body["allowed"]["promote_allowed"] is True
    assert "shadow_vs_primary_diff_recipe.sql" in body["recipe_path"]
