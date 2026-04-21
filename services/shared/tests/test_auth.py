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
    """Docker/K8s and scripts/ci/full_stack_smoke.py hit /v1/health without API keys."""
    monkeypatch.delenv("API_KEYS", raising=False)
    monkeypatch.delenv("ALLOW_INSECURE_NO_AUTH", raising=False)
    app = FastAPI(dependencies=[pytest.importorskip("fastapi").Depends(require_api_key)])

    @app.get("/v1/health")
    async def health():
        return {"status": "ok"}

    with TestClient(app) as client:
        resp = client.get("/v1/health")
    assert resp.status_code == 200
    assert resp.json().get("status") == "ok"


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
