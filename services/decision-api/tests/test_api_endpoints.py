"""Integration tests for Decision API endpoints using async ASGI client."""

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")

import httpx


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
            mock_redis.merge_tags = AsyncMock(return_value=["sdk:vpn"])
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
                        c.tarka_app = app
                        yield c
                    app.dependency_overrides = {}


class TestHealthEndpoint:
    @pytest.mark.asyncio
    async def test_health(self, client):
        r = await client.get("/v1/health")
        assert r.status_code == 200
        assert r.json()["status"] == "ok"


class TestAttestationChallenge:
    @pytest.mark.asyncio
    async def test_challenge(self, client):
        r = await client.post("/v1/attestation/challenge", json={"tenant_id": "t1"})
        assert r.status_code == 200
        data = r.json()
        assert "nonce" in data
        assert "expires_in" in data
        assert len(data["nonce"]) == 64


class TestAttestationVerify:
    @pytest.mark.asyncio
    async def test_verify_browser(self, client):
        r = await client.post("/v1/attestation/verify", json={"nonce": "abc123", "token": "tok", "provider": "browser_challenge"})
        assert r.status_code == 200
        assert r.json()["valid"] is True

    @pytest.mark.asyncio
    async def test_verify_expired_nonce(self, client):
        with patch("decision_api.main.redis_tags") as mock_redis:
            mock_redis.consume_nonce = AsyncMock(return_value=False)
            r = await client.post("/v1/attestation/verify", json={"nonce": "expired", "token": "tok", "provider": "browser_challenge"})
            assert r.status_code == 400


class TestEvaluateDecision:
    @pytest.mark.asyncio
    async def test_basic_allow(self, client):
        mock_session = AsyncMock()
        mock_session.add = MagicMock()
        mock_session.commit = AsyncMock()
        from decision_api.main import get_session

        with patch("decision_api.main.evaluate_json_rules", return_value=([], [], 0.0)):
            with patch("decision_api.main.evaluate_opa", new_callable=AsyncMock, return_value=None):
                with patch("decision_api.main._fetch_ml_score", new_callable=AsyncMock, return_value=(None, {})):
                    client.tarka_app.dependency_overrides[get_session] = _override_session_factory(mock_session)
                    r = await client.post("/v1/decisions/evaluate", json={"tenant_id": "t1", "event_type": "login", "entity_id": "u1", "payload": {}})
                    client.tarka_app.dependency_overrides.pop(get_session, None)
                    assert r.status_code == 200
                    data = r.json()
                    assert data["decision"] == "allow"
                    assert data["score"] <= 50
                    assert "trace_id" in data
                    assert "inference_context" in data
                    assert "integrity_confidence" in data["inference_context"]
                    assert 0 <= data["inference_context"]["integrity_confidence"] <= 1

    @pytest.mark.asyncio
    async def test_with_device_context(self, client):
        mock_session = AsyncMock()
        mock_session.add = MagicMock()
        mock_session.commit = AsyncMock()
        from decision_api.main import get_session

        with patch("decision_api.main.evaluate_json_rules", return_value=(["sdk_bot"], ["sdk:bot"], 40.0)):
            with patch("decision_api.main.evaluate_opa", new_callable=AsyncMock, return_value=None):
                with patch("decision_api.main._fetch_ml_score", new_callable=AsyncMock, return_value=(None, {})):
                    client.tarka_app.dependency_overrides[get_session] = _override_session_factory(mock_session)
                    r = await client.post(
                        "/v1/decisions/evaluate",
                        json={
                            "tenant_id": "t1",
                            "event_type": "payment",
                            "entity_id": "u1",
                            "payload": {"amount": 100},
                            "device_context": {
                                "device_id": "dev1",
                                "platform": "web",
                                "signals": {"is_bot": True},
                            },
                        },
                    )
                    client.tarka_app.dependency_overrides.pop(get_session, None)
                    assert r.status_code == 200
                    data = r.json()
                    assert "sdk_bot" in data["rule_hits"]
                    assert "inference_context" in data
                    assert "top_signals" in data["inference_context"]

    @pytest.mark.asyncio
    async def test_validation_error(self, client):
        r = await client.post("/v1/decisions/evaluate", json={"tenant_id": "t1"})
        assert r.status_code == 422


class TestAdminReload:
    @pytest.mark.asyncio
    async def test_reload_rules(self, client):
        with patch("decision_api.main.load_rules"):
            r = await client.post("/v1/admin/rules/reload")
            assert r.status_code == 200


class TestVerticalPacks:
    @pytest.mark.asyncio
    async def test_list_vertical_packs(self, client):
        r = await client.get("/v1/rules/vertical-packs")
        assert r.status_code == 200
        packs = r.json().get("vertical_packs", {})
        assert "fintech" in packs
        assert "ecommerce" in packs
        assert "gaming" in packs

    @pytest.mark.asyncio
    async def test_install_vertical_pack_and_conflict(self, client, tmp_path, monkeypatch):
        monkeypatch.setattr("decision_api.rule_api.settings.rules_path", str(tmp_path))
        with patch("decision_api.rule_api.load_rules"):
            first = await client.post("/v1/rules/vertical-packs/fintech/install")
            assert first.status_code == 201
            data = first.json()
            assert data["vertical"] == "fintech"
            assert data["rules"] >= 1

            second = await client.post("/v1/rules/vertical-packs/fintech/install")
            assert second.status_code == 409

            overwrite = await client.post("/v1/rules/vertical-packs/fintech/install", params={"overwrite": "true"})
            assert overwrite.status_code == 201

    @pytest.mark.asyncio
    async def test_install_unknown_vertical_pack(self, client):
        r = await client.post("/v1/rules/vertical-packs/unknown/install")
        assert r.status_code == 404

    @pytest.mark.asyncio
    async def test_benchmark_vertical_pack(self, client):
        r = await client.post(
            "/v1/simulation/benchmark/vertical",
            json={"scenario": "baseline", "vertical": "gaming"},
        )
        assert r.status_code == 200
        data = r.json()
        assert data["vertical"] == "gaming"
        assert "baseline" in data
        assert "vertical_pack" in data
        assert "delta" in data
        assert {"precision", "recall", "f1_score", "score_separation"} <= set(data["delta"].keys())


class TestAudit:
    @pytest.mark.asyncio
    async def test_audit_not_found(self, client):
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute = AsyncMock(return_value=mock_result)
        from decision_api.main import get_session

        client.tarka_app.dependency_overrides[get_session] = _override_session_factory(mock_session)
        r = await client.get(
            "/v1/audit/00000000-0000-0000-0000-000000000001",
            params={"tenant_id": "t1"},
        )
        client.tarka_app.dependency_overrides.pop(get_session, None)
        assert r.status_code == 404


async def _async_gen(value):
    yield value


def _override_session_factory(mock_session):
    async def _override():
        yield mock_session

    return _override
