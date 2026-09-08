"""G3: AuthMiddleware fail-closes when API_KEYS and OIDC are empty and insecure is off."""

from __future__ import annotations

import auth_rbac
from auth_rbac import setup_auth
from fastapi import FastAPI
from fastapi.testclient import TestClient


def _evaluate_app() -> FastAPI:
    app = FastAPI()
    setup_auth(app)

    @app.post("/v1/decisions/evaluate")
    async def evaluate():
        return {"decision": "ALLOW"}

    return app


def test_empty_api_keys_empty_oidc_insecure_off_evaluate_is_503(monkeypatch):
    monkeypatch.setenv("API_KEYS", "")
    monkeypatch.setenv("OIDC_ISSUER", "")
    monkeypatch.setenv("ALLOW_INSECURE_NO_AUTH", "false")
    monkeypatch.setenv("TARKA_DEPLOYMENT_PROFILE", "production")
    monkeypatch.setattr(auth_rbac, "OIDC_ISSUER", "")
    with TestClient(_evaluate_app()) as client:
        resp = client.post("/v1/decisions/evaluate", json={"event_id": "e1"})
    assert resp.status_code == 503
    assert "API_KEYS" in resp.json()["detail"] or "OIDC" in resp.json()["detail"]
    assert resp.json().get("decision") != "ALLOW"


def test_empty_keys_insecure_off_without_production_profile_is_still_503(monkeypatch):
    monkeypatch.setenv("API_KEYS", "")
    monkeypatch.setenv("OIDC_ISSUER", "")
    monkeypatch.setenv("ALLOW_INSECURE_NO_AUTH", "false")
    monkeypatch.delenv("TARKA_DEPLOYMENT_PROFILE", raising=False)
    monkeypatch.setattr(auth_rbac, "OIDC_ISSUER", "")
    with TestClient(_evaluate_app()) as client:
        resp = client.post("/v1/decisions/evaluate", json={"event_id": "e1"})
    assert resp.status_code == 503
