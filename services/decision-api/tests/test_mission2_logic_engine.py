"""Mission 2: rule compiler and gitops contract checks."""

import pytest
from httpx import ASGITransport, AsyncClient

from decision_api.main import app


@pytest.fixture
async def asgi_client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.mark.asyncio
async def test_compile_rego_transpiles_pack(
    asgi_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("API_KEYS", "k")
    monkeypatch.setenv("ALLOW_INSECURE_NO_AUTH", "false")
    payload = {
        "name": "demo",
        "rules": [
            {
                "id": "rule_one",
                "all_of": [{"field": "risk_score", "op": ">", "value": 0.9}],
                "any_of": [],
            }
        ],
        "tag_rules": [],
    }
    r = await asgi_client.post(
        "/v1/rules/visual/compile/rego",
        headers={"x-api-key": "k"},
        json=payload,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["package"] == "tarka.visual"
    assert 'rules contains "rule_one"' in body["rego_module"]
    assert "input.risk_score > 0.9" in body["rego_module"]
