from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from tenant_binding import enforce_tenant_access, tenant_binding_required


def _client(monkeypatch, *, required: bool) -> TestClient:
    monkeypatch.setenv("TENANT_BINDING_REQUIRED", "true" if required else "false")
    app = FastAPI()

    @app.get("/cases")
    async def list_cases(request: Request):
        await enforce_tenant_access(request, allowed_tenants={"tenant_alpha"})
        return {"ok": True}

    @app.get("/v1/health")
    async def health(request: Request):
        await enforce_tenant_access(request, allowed_tenants={"tenant_alpha"})
        return {"status": "ok"}

    return TestClient(app)


def test_missing_tenant_fails_closed_when_required(monkeypatch):
    client = _client(monkeypatch, required=True)
    resp = client.get("/cases")
    assert resp.status_code == 400
    assert "tenant_id" in resp.json()["detail"]


def test_missing_tenant_passes_when_not_required(monkeypatch):
    client = _client(monkeypatch, required=False)
    resp = client.get("/cases")
    assert resp.status_code == 200


def test_present_tenant_allowed(monkeypatch):
    client = _client(monkeypatch, required=True)
    resp = client.get("/cases", params={"tenant_id": "tenant_alpha"})
    assert resp.status_code == 200


def test_header_tenant_allowed(monkeypatch):
    client = _client(monkeypatch, required=True)
    resp = client.get("/cases", headers={"x-tenant-id": "tenant_alpha"})
    assert resp.status_code == 200


def test_cross_tenant_forbidden(monkeypatch):
    client = _client(monkeypatch, required=True)
    resp = client.get("/cases", params={"tenant_id": "tenant_beta"})
    assert resp.status_code == 403


def test_health_probe_skips_binding(monkeypatch):
    client = _client(monkeypatch, required=True)
    resp = client.get("/v1/health")
    assert resp.status_code == 200


def test_flag_parser(monkeypatch):
    monkeypatch.setenv("TENANT_BINDING_REQUIRED", "true")
    assert tenant_binding_required() is True
    monkeypatch.setenv("TENANT_BINDING_REQUIRED", "0")
    assert tenant_binding_required() is False
