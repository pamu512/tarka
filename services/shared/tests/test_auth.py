from __future__ import annotations

import pytest
from auth import require_api_key
from fastapi import FastAPI
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def _reset_auth_cache():
    # auth.py reads API_KEYS per request; keep fixture for compatibility with old tests.
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

    for path in (
        "/v1/health",
        "/v1/ready",
        "/v1/health/deep",
        "/health",
        "/health/deep",
    ):
        app.add_api_route(path, health, methods=["GET"])

    with TestClient(app) as client:
        for path in (
            "/v1/health",
            "/v1/ready",
            "/v1/health/deep",
            "/health",
            "/health/deep",
        ):
            resp = client.get(path)
            assert resp.status_code == 200, path
            assert resp.json().get("status") == "ok", path


def test_secure_api_keys_still_exempt_only_probe_routes(monkeypatch):
    monkeypatch.setenv("API_KEYS", "secure-key")
    monkeypatch.setenv("API_KEY_TENANT_MAP", '{"secure-key":["t1"]}')
    monkeypatch.delenv("ALLOW_INSECURE_NO_AUTH", raising=False)
    app = FastAPI(dependencies=[pytest.importorskip("fastapi").Depends(require_api_key)])

    async def ok():
        return {"status": "ok"}

    app.add_api_route("/v1/health", ok, methods=["GET"])
    app.add_api_route("/v1/ready", ok, methods=["GET"])
    app.add_api_route("/v1/health/deep", ok, methods=["GET"])
    app.add_api_route("/health", ok, methods=["GET"])
    app.add_api_route("/health/deep", ok, methods=["GET"])
    app.add_api_route("/protected", ok, methods=["GET"])

    with TestClient(app) as client:
        assert client.get("/v1/health").status_code == 200
        assert client.get("/v1/ready").status_code == 200
        assert client.get("/v1/health/deep").status_code == 200
        assert client.get("/health").status_code == 200
        assert client.get("/health/deep").status_code == 200
        assert client.get("/protected").status_code == 401
        assert client.get("/protected", headers={"x-api-key": "secure-key"}).status_code == 200


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
