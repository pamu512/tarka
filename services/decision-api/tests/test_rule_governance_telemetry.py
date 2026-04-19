"""N2 rule governance header and N3/N4 telemetry endpoint."""

import os
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")


@pytest.fixture(autouse=True)
def _patch_env(monkeypatch):
    monkeypatch.setenv("API_KEYS", "")
    monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")


@pytest.fixture
async def client():
    with patch("decision_api.main.init_db", new_callable=AsyncMock):
        with patch("decision_api.main.redis_tags") as mock_redis:
            mock_redis.connect = AsyncMock()
            mock_redis.close = AsyncMock()
            mock_redis._client = MagicMock()
            mock_redis.get_tags = AsyncMock(return_value=[])
            mock_redis.merge_tags = AsyncMock(return_value=[])
            mock_redis.set_cached_score = AsyncMock()
            mock_redis.store_nonce = AsyncMock()
            mock_redis.consume_nonce = AsyncMock(return_value=True)
            mock_redis.check_and_store_replay_signature = AsyncMock(return_value=False)

            with patch("decision_api.main.load_rules"):
                with patch("decision_api.main.agg_store") as mock_agg:
                    mock_agg._client = None
                    from decision_api.main import app

                    app.state.http = AsyncMock()
                    app.state.nats_js = None
                    app.state.nats_nc = None
                    app.dependency_overrides = {}
                    transport = httpx.ASGITransport(app=app)
                    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as c:
                        yield c
                    app.dependency_overrides = {}


class TestRuleGovernanceSecret:
    @pytest.mark.asyncio
    async def test_mutate_without_secret_403_when_configured(self, client, monkeypatch):
        from decision_api import rule_api

        monkeypatch.setattr(rule_api.settings, "rule_governance_secret", "test-secret-99")
        r = await client.post("/v1/rules", json={"name": "Governed Pack", "rules": [], "tag_rules": []})
        assert r.status_code == 403

    @pytest.mark.asyncio
    async def test_mutate_with_secret_ok(self, client, monkeypatch, tmp_path):
        from decision_api import rule_api

        monkeypatch.setattr(rule_api.settings, "rules_path", str(tmp_path))
        monkeypatch.setattr(rule_api.settings, "rule_governance_secret", "test-secret-99")
        r = await client.post(
            "/v1/rules",
            json={"name": "Governed Pack Z", "rules": [], "tag_rules": []},
            headers={"X-Rule-Governance-Secret": "test-secret-99"},
        )
        assert r.status_code == 201
        data = r.json()
        assert "file" in data


class TestRuleTelemetryEndpoint:
    @pytest.mark.asyncio
    async def test_telemetry_get(self, client):
        r = await client.get("/v1/rules/telemetry")
        assert r.status_code == 200
        data = r.json()
        assert "since_unix" in data
        assert "total_hits" in data
        assert "rows" in data
