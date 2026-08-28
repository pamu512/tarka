"""Local desk: API_KEYS + ALLOW_INSECURE_NO_AUTH — viewer without key, analyst with seed key.

Production profile must still fail closed (no anonymous elevation).
"""

from __future__ import annotations

import pytest
from auth_rbac import require_role, setup_auth
from fastapi import Depends, FastAPI, Request
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    monkeypatch.delenv("OIDC_ISSUER", raising=False)
    monkeypatch.setenv("TENANT_BINDING_REQUIRED", "false")
    monkeypatch.delenv("TARKA_DEPLOYMENT_PROFILE", raising=False)
    yield


def _app() -> FastAPI:
    app = FastAPI()
    setup_auth(app)

    @app.get("/whoami")
    async def whoami(request: Request):
        user = request.state.auth_user
        return {"user_id": user.user_id, "roles": user.roles, "best_role": user.best_role}

    @app.get("/analyst-only", dependencies=[Depends(require_role("analyst"))])
    async def analyst_only():
        return {"ok": True}

    return app


def test_insecure_plus_api_keys_anonymous_stays_viewer(monkeypatch):
    monkeypatch.setenv("ALLOW_INSECURE_NO_AUTH", "true")
    monkeypatch.setenv("API_KEYS", "desk-analyst-local")
    monkeypatch.setenv("SERVICE_API_KEY_ROLE", "analyst")
    with TestClient(_app(), raise_server_exceptions=False) as c:
        who = c.get("/whoami")
        denied = c.get("/analyst-only")
    assert who.status_code == 200, who.text
    assert who.json()["best_role"] == "viewer"
    assert denied.status_code == 403


def test_insecure_plus_seed_key_grants_analyst(monkeypatch):
    monkeypatch.setenv("ALLOW_INSECURE_NO_AUTH", "true")
    monkeypatch.setenv("API_KEYS", "desk-analyst-local")
    monkeypatch.setenv("SERVICE_API_KEY_ROLE", "analyst")
    with TestClient(_app()) as c:
        who = c.get("/whoami", headers={"x-api-key": "desk-analyst-local"})
        ok = c.get("/analyst-only", headers={"x-api-key": "desk-analyst-local"})
    assert who.status_code == 200, who.text
    assert who.json()["best_role"] == "analyst"
    assert ok.status_code == 200


def test_wrong_key_is_401_even_when_insecure(monkeypatch):
    monkeypatch.setenv("ALLOW_INSECURE_NO_AUTH", "true")
    monkeypatch.setenv("API_KEYS", "desk-analyst-local")
    with TestClient(_app(), raise_server_exceptions=False) as c:
        r = c.get("/whoami", headers={"x-api-key": "not-the-seed"})
    assert r.status_code == 401


def test_production_profile_does_not_grant_anonymous_viewer_when_keys_set(monkeypatch):
    monkeypatch.setenv("TARKA_DEPLOYMENT_PROFILE", "production")
    monkeypatch.setenv("ALLOW_INSECURE_NO_AUTH", "true")
    monkeypatch.setenv("API_KEYS", "desk-analyst-local")
    with TestClient(_app(), raise_server_exceptions=False) as c:
        r = c.get("/whoami")
    assert r.status_code == 401


def test_insecure_off_with_api_keys_no_header_is_401(monkeypatch):
    monkeypatch.setenv("ALLOW_INSECURE_NO_AUTH", "false")
    monkeypatch.setenv("API_KEYS", "desk-analyst-local")
    with TestClient(_app(), raise_server_exceptions=False) as c:
        r = c.get("/whoami")
    assert r.status_code == 401


def test_insecure_does_not_bypass_oidc(monkeypatch):
    monkeypatch.setenv("ALLOW_INSECURE_NO_AUTH", "true")
    monkeypatch.setenv("API_KEYS", "desk-analyst-local")
    monkeypatch.setenv("OIDC_ISSUER", "https://idp.example")
    with TestClient(_app(), raise_server_exceptions=False) as c:
        r = c.get("/whoami")
    assert r.status_code == 401
