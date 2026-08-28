"""Desk override: why required; viewer 403; analyst persists why as a label."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from auth_rbac import AuthUser
from decision_api.decision_override import router as override_router
from decision_api.y_label_store import load_override_whys, load_y_labels


def _app_as(roles: list[str]) -> FastAPI:
    app = FastAPI()

    @app.middleware("http")
    async def _inject_auth(request, call_next):
        request.state.auth_user = AuthUser("test-user", roles, "test", tenant_ids={"*"})
        return await call_next(request)

    app.include_router(override_router)
    return app


@pytest.fixture
def tmp_cal(tmp_path, monkeypatch):
    monkeypatch.setenv("CALIBRATION_DATA_DIR", str(tmp_path))
    return tmp_path


@pytest.mark.asyncio
async def test_override_without_why_rejected(tmp_cal):
    transport = ASGITransport(app=_app_as(["analyst"]))
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.post(
            "/v1/calibration/y-labels/override",
            json={
                "tenant_id": "demo",
                "trace_id": "tr-flag-1",
                "entity_id": "desk-login-1",
                "y_label": "LEGITIMATE",
                "why": "   ",
            },
        )
    assert r.status_code == 422 or r.status_code == 400
    stored = load_y_labels("demo")
    assert stored["by_trace"] == {}
    assert load_override_whys("demo") == {}


@pytest.mark.asyncio
async def test_viewer_cannot_override(tmp_cal):
    transport = ASGITransport(app=_app_as(["viewer"]))
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.post(
            "/v1/calibration/y-labels/override",
            json={
                "tenant_id": "demo",
                "trace_id": "tr-flag-1",
                "entity_id": "desk-login-1",
                "y_label": "LEGITIMATE",
                "why": "Known contractor VPN",
            },
        )
    assert r.status_code == 403
    stored = load_y_labels("demo")
    assert stored["by_trace"] == {}


@pytest.mark.asyncio
async def test_analyst_override_persists_why_as_label(tmp_cal):
    transport = ASGITransport(app=_app_as(["analyst"]))
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.post(
            "/v1/calibration/y-labels/override",
            json={
                "tenant_id": "demo",
                "trace_id": "tr-flag-1",
                "entity_id": "desk-login-1",
                "y_label": "LEGITIMATE",
                "why": "Known contractor VPN",
            },
        )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert body["learned"] is False
    stored = load_y_labels("demo")
    assert stored["by_trace"]["tr-flag-1"] == "0"
    assert stored["by_entity"]["desk-login-1"] == "0"
    assert load_override_whys("demo")["tr-flag-1"] == "Known contractor VPN"
