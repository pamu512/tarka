"""P1-FSC: feature serving contract discoverability."""

from __future__ import annotations

import os

import pytest
from httpx import ASGITransport, AsyncClient


@pytest.mark.asyncio
async def test_feature_serving_contract():
    os.environ["ALLOW_INSECURE_NO_AUTH"] = "true"
    from feature_service.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/v1/feature-serving-contract")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["schema_id"] == "tarka.feature_serving_contract/v1"
    assert body["online_store"] == "redis_aggregates"
    assert "parity" in body["offline_parity"]["endpoint"] or "parity" in body["offline_parity"]["job"]
    assert "zero_fallback_on_miss" in body
