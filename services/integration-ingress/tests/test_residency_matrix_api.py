"""GET/PUT /v1/compliance/residency/matrix (compliance_residency.py)."""

from __future__ import annotations

import os

import pytest
from httpx import ASGITransport, AsyncClient


@pytest.mark.asyncio
async def test_residency_matrix_get_and_put_roundtrip(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    from integration_ingress.compliance_residency import init_residency_matrix_store
    from integration_ingress.config import settings
    from integration_ingress.main import app

    p = tmp_path / "matrix.json"
    monkeypatch.setattr(settings, "residency_matrix_json_path", str(p))
    init_residency_matrix_store(json_path=str(p))

    transport = ASGITransport(app=app)
    key = (os.environ.get("API_KEYS") or "").split(",")[0].strip()
    headers = {"X-API-Key": key}

    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            g = await client.get("/v1/compliance/residency/matrix", headers=headers)
        assert g.status_code == 200, g.text
        body = g.json()
        assert "tenants" in body and "vendors" in body and "cells" in body
        assert isinstance(body["cells"], dict)

        async with AsyncClient(transport=transport, base_url="http://test") as client:
            r = await client.put(
                "/v1/compliance/residency/matrix",
                headers=headers,
                json={"tenant_id": "demo", "vendor_key": "shodan", "blocked": True},
            )
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["cells"].get("demo::shodan") is True

        async with AsyncClient(transport=transport, base_url="http://test") as client:
            g2 = await client.get("/v1/compliance/residency/matrix", headers=headers)
        assert g2.json()["cells"].get("demo::shodan") is True

        async with AsyncClient(transport=transport, base_url="http://test") as client:
            r2 = await client.put(
                "/v1/compliance/residency/matrix",
                headers=headers,
                json={"tenant_id": "demo", "vendor_key": "shodan", "blocked": False},
            )
        assert r2.status_code == 200
        assert "demo::shodan" not in (r2.json().get("cells") or {})
    finally:
        init_residency_matrix_store(json_path="")


@pytest.mark.asyncio
async def test_residency_matrix_put_rejects_unknown_vendor(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    from integration_ingress.compliance_residency import init_residency_matrix_store
    from integration_ingress.config import settings
    from integration_ingress.main import app

    monkeypatch.setattr(settings, "residency_matrix_json_path", str(tmp_path / "m2.json"))
    init_residency_matrix_store(json_path=str(tmp_path / "m2.json"))

    transport = ASGITransport(app=app)
    key = (os.environ.get("API_KEYS") or "").split(",")[0].strip()
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            r = await client.put(
                "/v1/compliance/residency/matrix",
                headers={"X-API-Key": key},
                json={"tenant_id": "demo", "vendor_key": "not_a_real_vendor", "blocked": True},
            )
        assert r.status_code == 400
    finally:
        init_residency_matrix_store(json_path="")
