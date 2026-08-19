"""CASE_INTERNAL_TOKEN S2S auth via X-Internal-Token header."""

from __future__ import annotations

import pytest
from auth_rbac import AuthMiddleware, require_role, setup_auth
from fastapi import Depends, FastAPI, Request
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    monkeypatch.delenv("API_KEYS", raising=False)
    monkeypatch.delenv("OIDC_ISSUER", raising=False)
    monkeypatch.setenv("ALLOW_INSECURE_NO_AUTH", "true")
    monkeypatch.setenv("TENANT_BINDING_REQUIRED", "false")
    yield


def _app(monkeypatch, token: str) -> FastAPI:
    monkeypatch.setenv("CASE_INTERNAL_TOKEN", token)
    app = FastAPI()
    setup_auth(app)

    @app.get("/analyst-only", dependencies=[Depends(require_role("analyst"))])
    async def analyst_only(request: Request):
        user = request.state.auth_user
        return {"user_id": user.user_id, "roles": user.roles, "auth_type": user.auth_type}

    @app.get("/viewer-ok")
    async def viewer_ok():
        return {"ok": True}

    return app


def test_internal_token_grants_analyst(monkeypatch):
    app = _app(monkeypatch, "s2s-secret")
    with TestClient(app) as c:
        r = c.get("/analyst-only", headers={"X-Internal-Token": "s2s-secret"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["auth_type"] == "internal_token"
    assert "analyst" in body["roles"]


def test_internal_token_wrong_value_falls_through(monkeypatch):
    app = _app(monkeypatch, "s2s-secret")
    with TestClient(app) as c:
        r = c.get("/analyst-only", headers={"X-Internal-Token": "wrong"})
    assert r.status_code == 403


def test_no_internal_token_anonymous_viewer(monkeypatch):
    app = _app(monkeypatch, "s2s-secret")
    with TestClient(app) as c:
        r = c.get("/analyst-only")
    assert r.status_code == 403


def test_viewer_still_works_without_token(monkeypatch):
    app = _app(monkeypatch, "s2s-secret")
    with TestClient(app) as c:
        r = c.get("/viewer-ok")
    assert r.status_code == 200


def test_internal_token_empty_env_means_disabled(monkeypatch):
    """When CASE_INTERNAL_TOKEN is empty, X-Internal-Token header is ignored."""
    app = _app(monkeypatch, "")
    with TestClient(app) as c:
        r = c.get("/analyst-only", headers={"X-Internal-Token": "anything"})
    assert r.status_code == 403
