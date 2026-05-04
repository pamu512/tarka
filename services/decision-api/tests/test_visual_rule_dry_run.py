"""POST /v1/rules/visual/evaluate-dry-run — ad-hoc Rust evaluation of canvas-compiled rules."""

import pytest
from httpx import ASGITransport, AsyncClient

from decision_api.main import app


@pytest.fixture
async def asgi_client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.mark.asyncio
async def test_evaluate_visual_dry_run_rule_hit(asgi_client: AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("API_KEYS", "k")
    monkeypatch.setenv("ALLOW_INSECURE_NO_AUTH", "false")
    body = {
        "visual_pack": {
            "name": "dry_pack",
            "rules": [
                {
                    "id": "high_amount",
                    "all_of": [{"field": "transaction_amount", "op": "gte", "value": 5000}],
                    "any_of": [],
                    "tags": ["t:hit"],
                    "score_delta": 12,
                    "description": "",
                }
            ],
            "tag_rules": [],
        },
        "features": {"transaction_amount": 9000},
        "redis_tags": [],
    }
    r = await asgi_client.post("/v1/rules/visual/evaluate-dry-run", headers={"x-api-key": "k"}, json=body)
    assert r.status_code == 200, r.text
    data = r.json()
    assert "high_amount" in data["rule_hits"]
    assert data["score_delta"] == 12.0
    assert data["compiled_rules"][0]["when"][0]["field"] == "transaction_amount"
