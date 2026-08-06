"""POST /v1/calibration/challenge/dispatch contract (Engineering 4.7)."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from decision_api.calibration_api import router as calibration_router


@pytest.fixture
async def challenge_client(monkeypatch):
    monkeypatch.delenv("TARKA_CHALLENGE_WEBHOOK_URL", raising=False)
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
async def test_challenge_dispatch_rejects_non_step_up(challenge_client):
    r = await challenge_client.post(
        "/v1/calibration/challenge/dispatch",
        json={
            "tenant_id": "demo",
            "trace_id": "t1",
            "entity_id": "e1",
            "decision": "review",
            "recommended_action": "manual_review",
        },
    )
    assert r.status_code == 400, r.text
    detail = r.json().get("detail") or {}
    assert isinstance(detail, dict)
    assert detail.get("reason_code") == "NOT_STEP_UP_ACTION"


@pytest.mark.asyncio
async def test_challenge_dispatch_503_when_webhook_unset(challenge_client):
    r = await challenge_client.post(
        "/v1/calibration/challenge/dispatch",
        json={
            "tenant_id": "demo",
            "trace_id": "t1",
            "entity_id": "e1",
            "decision": "review",
            "recommended_action": "step_up_mfa",
        },
    )
    assert r.status_code == 503, r.text
    detail = r.json().get("detail") or {}
    assert isinstance(detail, dict)
    assert detail.get("reason_code") == "CHALLENGE_WEBHOOK_UNCONFIGURED"


@pytest.mark.asyncio
async def test_challenge_dispatch_ok_when_webhook_configured(monkeypatch):
    monkeypatch.setenv("TARKA_CHALLENGE_WEBHOOK_URL", "https://example.test/challenge")
    monkeypatch.setenv("ALLOW_INSECURE_NO_AUTH", "true")

    class _Resp:
        status_code = 200
        text = "ok"

        def raise_for_status(self):
            return None

    class _Http:
        async def post(self, url, json=None, headers=None, timeout=None):
            assert url == "https://example.test/challenge"
            assert json["schema_id"] == "tarka.challenge_webhook/v1"
            return _Resp()

    # If orchestrator uses httpx.AsyncClient context manager, patch at call site:
    import decision_api.challenge_orchestrator as orch

    async def _fake_dispatch(**kwargs):
        return {"ok": True, "status_code": 200, "url": "https://example.test/challenge"}

    monkeypatch.setattr(orch, "maybe_dispatch_challenge_webhook", _fake_dispatch)

    from auth_rbac import AuthUser
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient
    from decision_api.calibration_api import router as calibration_router

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
        r = await client.post(
            "/v1/calibration/challenge/dispatch",
            json={
                "tenant_id": "demo",
                "trace_id": "t1",
                "entity_id": "e1",
                "decision": "review",
                "recommended_action": "step_up_mfa",
            },
        )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body.get("ok") is True
    assert body.get("delivery", {}).get("ok") is True
