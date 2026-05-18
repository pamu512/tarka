"""Refund Swatter #59 / epic #58: BYOK install validation and policy document."""

import os

import pytest
from fastapi import HTTPException
from integration_ingress.byok_policy import policy_document, validate_install_config


def test_validate_rejects_platform_custody_keys():
    with pytest.raises(HTTPException) as ei:
        validate_install_config({"api_key": "x", "platform_api_key": "nope"})
    assert ei.value.status_code == 400
    assert "byok_policy_violation" in str(ei.value.detail)


def test_policy_document_shape():
    doc = policy_document(
        providers=[
            {
                "id": "stripe_radar",
                "name": "Stripe",
                "category": "payments",
                "doc_url": "https://stripe.com/docs/radar",
            }
        ]
    )
    assert doc["schema"] == "tarka.byok_policy/v1"
    assert doc["version"] == 1
    assert "secret_storage_rules" in doc
    prov = doc["providers"][0]
    assert prov["id"] == "stripe_radar"
    assert prov["byok_capabilities"]["tenant_owned_material"] is True


@pytest.mark.asyncio
async def test_byok_policy_http():
    from unittest.mock import AsyncMock, MagicMock, patch

    with patch("integration_ingress.main.init_db", new_callable=AsyncMock):
        from integration_ingress.main import app, get_session

        session = MagicMock()
        session.add = MagicMock()
        session.commit = AsyncMock()
        session.execute = AsyncMock()

        async def _override():
            yield session

        app.dependency_overrides[get_session] = _override
        import httpx

        transport = httpx.ASGITransport(app=app)
        key = (os.environ.get("API_KEYS") or "").split(",")[0].strip()
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test", headers={"X-API-Key": key}
        ) as c:
            r = await c.get("/v1/vault/byok-policy")
        app.dependency_overrides = {}
    assert r.status_code == 200
    assert r.json()["schema"] == "tarka.byok_policy/v1"
