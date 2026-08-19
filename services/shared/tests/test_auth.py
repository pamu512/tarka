from __future__ import annotations

import pytest
from auth import require_api_key
from fastapi import FastAPI
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def _reset_auth_cache(monkeypatch):
    # CI matrix sets TENANT_BINDING_REQUIRED=true; these tests are API-key only.
    monkeypatch.setenv("TENANT_BINDING_REQUIRED", "false")
    yield


def _build_app() -> FastAPI:
    app = FastAPI(dependencies=[])

    @app.get("/protected")
    async def protected():
        return {"ok": True}

    app.dependency_overrides = {}
    app.dependency_overrides[require_api_key] = require_api_key
    return app


def test_require_api_key_fails_closed_when_unconfigured(monkeypatch):
    monkeypatch.delenv("API_KEYS", raising=False)
    monkeypatch.delenv("ALLOW_INSECURE_NO_AUTH", raising=False)
    app = FastAPI(dependencies=[pytest.importorskip("fastapi").Depends(require_api_key)])

    @app.get("/protected")
    async def protected():
        return {"ok": True}

    with TestClient(app) as client:
        resp = client.get("/protected")
    assert resp.status_code == 503


def test_require_api_key_skips_health_for_probes(monkeypatch):
    """Docker/K8s and scripts probe shallow/deep health without API keys."""
    monkeypatch.delenv("API_KEYS", raising=False)
    monkeypatch.delenv("ALLOW_INSECURE_NO_AUTH", raising=False)
    app = FastAPI(dependencies=[pytest.importorskip("fastapi").Depends(require_api_key)])

    async def health():
        return {"status": "ok"}

    for path in ("/v1/health", "/v1/health/deep", "/health/deep"):
        app.add_api_route(path, health, methods=["GET"])

    with TestClient(app) as client:
        for path in ("/v1/health", "/v1/health/deep", "/health/deep"):
            resp = client.get(path)
            assert resp.status_code == 200, path
            assert resp.json().get("status") == "ok", path


def test_require_api_key_allows_explicit_insecure_dev(monkeypatch):
    monkeypatch.delenv("API_KEYS", raising=False)
    monkeypatch.setenv("ALLOW_INSECURE_NO_AUTH", "true")
    app = FastAPI(dependencies=[pytest.importorskip("fastapi").Depends(require_api_key)])

    @app.get("/protected")
    async def protected():
        return {"ok": True}

    with TestClient(app) as client:
        resp = client.get("/protected")
    assert resp.status_code == 200


def test_require_api_key_enforces_valid_header(monkeypatch):
    monkeypatch.setenv("API_KEYS", "k1")
    monkeypatch.delenv("ALLOW_INSECURE_NO_AUTH", raising=False)
    app = FastAPI(dependencies=[pytest.importorskip("fastapi").Depends(require_api_key)])

    @app.get("/protected")
    async def protected():
        return {"ok": True}

    with TestClient(app) as client:
        bad = client.get("/protected")
        good = client.get("/protected", headers={"x-api-key": "k1"})
    assert bad.status_code == 401
    assert good.status_code == 200


def test_production_profile_refuses_insecure_even_when_flag_set(monkeypatch):
    monkeypatch.delenv("API_KEYS", raising=False)
    monkeypatch.setenv("ALLOW_INSECURE_NO_AUTH", "true")
    monkeypatch.setenv("TARKA_DEPLOYMENT_PROFILE", "production")
    app = FastAPI(dependencies=[pytest.importorskip("fastapi").Depends(require_api_key)])

    @app.get("/protected")
    async def protected():
        return {"ok": True}

    with TestClient(app) as client:
        resp = client.get("/protected")
    assert resp.status_code == 503


def test_production_profile_empty_keys_503_without_oidc(monkeypatch):
    monkeypatch.delenv("API_KEYS", raising=False)
    monkeypatch.delenv("ALLOW_INSECURE_NO_AUTH", raising=False)
    monkeypatch.delenv("OIDC_ISSUER", raising=False)
    monkeypatch.setenv("TARKA_DEPLOYMENT_PROFILE", "production")
    app = FastAPI(dependencies=[pytest.importorskip("fastapi").Depends(require_api_key)])

    @app.get("/protected")
    async def protected():
        return {"ok": True}

    with TestClient(app) as client:
        resp = client.get("/protected")
    assert resp.status_code == 503


def _protected_app():
    app = FastAPI(dependencies=[pytest.importorskip("fastapi").Depends(require_api_key)])

    @app.get("/protected")
    async def protected():
        return {"ok": True}

    return app


def test_empty_map_binding_required_is_503(monkeypatch):
    monkeypatch.setenv("API_KEYS", "k1")
    monkeypatch.setenv("TENANT_BINDING_REQUIRED", "true")
    monkeypatch.delenv("API_KEY_TENANT_MAP", raising=False)
    monkeypatch.delenv("ALLOW_INSECURE_NO_AUTH", raising=False)
    with TestClient(_protected_app()) as client:
        resp = client.get(
            "/protected",
            headers={"x-api-key": "k1", "x-tenant-id": "tenant_alpha"},
        )
    assert resp.status_code == 503
    assert "API_KEY_TENANT_MAP" in resp.json()["detail"]


def test_bad_json_tenant_map_is_503(monkeypatch):
    monkeypatch.setenv("API_KEYS", "k1")
    monkeypatch.setenv("TENANT_BINDING_REQUIRED", "true")
    monkeypatch.setenv("API_KEY_TENANT_MAP", "{not-json")
    monkeypatch.delenv("ALLOW_INSECURE_NO_AUTH", raising=False)
    with TestClient(_protected_app()) as client:
        resp = client.get(
            "/protected",
            headers={"x-api-key": "k1", "x-tenant-id": "tenant_alpha"},
        )
    assert resp.status_code == 503
    assert "JSON" in resp.json()["detail"]


def test_valid_map_allows_listed_tenant(monkeypatch):
    monkeypatch.setenv("API_KEYS", "k1")
    monkeypatch.setenv("TENANT_BINDING_REQUIRED", "true")
    monkeypatch.setenv("API_KEY_TENANT_MAP", '{"k1": "tenant_alpha"}')
    monkeypatch.delenv("ALLOW_INSECURE_NO_AUTH", raising=False)
    with TestClient(_protected_app()) as client:
        good = client.get(
            "/protected",
            headers={"x-api-key": "k1", "x-tenant-id": "tenant_alpha"},
        )
        denied = client.get(
            "/protected",
            headers={"x-api-key": "k1", "x-tenant-id": "tenant_beta"},
        )
    assert good.status_code == 200
    assert denied.status_code == 403


def test_wildcard_map_rejected_in_production_profile(monkeypatch):
    monkeypatch.setenv("API_KEYS", "k1")
    monkeypatch.setenv("TENANT_BINDING_REQUIRED", "true")
    monkeypatch.setenv("TARKA_DEPLOYMENT_PROFILE", "production")
    monkeypatch.setenv("API_KEY_TENANT_MAP", '{"k1": "*"}')
    monkeypatch.delenv("ALLOW_INSECURE_NO_AUTH", raising=False)
    with TestClient(_protected_app()) as client:
        resp = client.get(
            "/protected",
            headers={"x-api-key": "k1", "x-tenant-id": "tenant_alpha"},
        )
    assert resp.status_code == 503
    assert "*" in resp.json()["detail"]
