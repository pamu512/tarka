"""Integration tests for Decision API endpoints using async ASGI client."""

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")

import httpx


@pytest.fixture(autouse=True)
def _patch_env(monkeypatch):
    monkeypatch.setenv("API_KEYS", "test-key")
    monkeypatch.delenv("ALLOW_INSECURE_NO_AUTH", raising=False)
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
                        c.headers.update({"x-api-key": "test-key"})
                        c.tarka_app = app
                        yield c
                    app.dependency_overrides = {}


class TestHealthEndpoint:
    @pytest.mark.asyncio
    async def test_health(self, client):
        r = await client.get("/v1/slo")
        assert r.status_code == 200
        slo = r.json()
        assert slo.get("service") == "decision-api"
        assert "current" in slo

        r = await client.get("/v1/health")
        assert r.status_code == 200
        assert r.json()["status"] == "ok"


class TestEvaluationPosture:
    @pytest.mark.asyncio
    async def test_evaluation_posture_shape(self, client):
        r = await client.get("/v1/ops/evaluation-posture")
        assert r.status_code == 200
        body = r.json()
        assert body.get("service") == "decision-api"
        assert body.get("deployment_tier") in {"community", "pro"}
        assert body.get("evaluation_mode") in {"detection", "compliance"}
        assert "compliance_degraded" in body
        assert "dependencies" in body and isinstance(body["dependencies"], list)
        assert "typology_count" in body
        assert "predicate_registry_version" in body
        assert body.get("tenant_reliability_profile") in {"strict", "balanced", "permissive"}


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
        captured: list = []

        def _capture_add(obj):
            captured.append(obj)

        mock_session.add = MagicMock(side_effect=_capture_add)
        mock_session.commit = AsyncMock()
        from decision_api.main import get_session

        with patch("decision_api.main.evaluate_json_rules", return_value=([], [], 0.0, [])):
            with patch("decision_api.main.evaluate_opa_or_raise", new_callable=AsyncMock, return_value=None):
                with patch("decision_api.main._fetch_ml_score_wrapped", new_callable=AsyncMock, return_value=(None, {})):
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
                    audit = mock_session.add.call_args[0][0]
                    snap0 = audit.payload_snapshot or {}
                    assert "canary_cohort" in snap0
                    assert snap0.get("counter_version") == "default"
                    assert snap0.get("rule_pack_file") == ""
                    assert "ml_model" in snap0

    @pytest.mark.asyncio
    async def test_with_device_context(self, client):
        mock_session = AsyncMock()
        mock_session.add = MagicMock()
        mock_session.commit = AsyncMock()
        from decision_api.main import get_session

        with patch("decision_api.main.evaluate_json_rules", return_value=(["sdk_bot"], ["sdk:bot"], 40.0, [])):
            with patch("decision_api.main.evaluate_opa_or_raise", new_callable=AsyncMock, return_value=None):
                with patch("decision_api.main._fetch_ml_score_wrapped", new_callable=AsyncMock, return_value=(None, {})):
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
    async def test_with_agent_context(self, client):
        mock_session = AsyncMock()
        mock_session.add = MagicMock()
        mock_session.commit = AsyncMock()
        from decision_api.main import get_session

        captured_features: dict = {}

        def _capture_rules(features, *_args, **_kwargs):
            captured_features.update(dict(features) if features else {})
            return ([], [], 0.0, [])

        with patch("decision_api.main.evaluate_json_rules", side_effect=_capture_rules):
            with patch("decision_api.main.evaluate_opa_or_raise", new_callable=AsyncMock, return_value=None):
                with patch("decision_api.main._fetch_ml_score_wrapped", new_callable=AsyncMock, return_value=(None, {})):
                    client.tarka_app.dependency_overrides[get_session] = _override_session_factory(mock_session)
                    ac = {
                        "agent_session_id": "asess-test",
                        "agent_client": {"oauth_client_id": "reg-client-1", "client_type": "mcp"},
                        "integrity": {"prompt_injection_heuristic_flag": False},
                    }
                    r = await client.post(
                        "/v1/decisions/evaluate",
                        json={
                            "tenant_id": "t1",
                            "event_type": "payment",
                            "entity_id": "u1",
                            "payload": {"amount": 10},
                            "metadata": {"correlation_id": "corr-xyz"},
                            "agent_context": ac,
                        },
                    )
                    client.tarka_app.dependency_overrides.pop(get_session, None)
                    assert r.status_code == 200
                    assert captured_features.get("agent_context", {}).get("agent_client", {}).get("oauth_client_id") == "reg-client-1"
                    audit = mock_session.add.call_args[0][0]
                    snap = audit.payload_snapshot or {}
                    assert snap.get("agent_context", {}).get("agent_session_id") == "asess-test"

    @pytest.mark.asyncio
    async def test_validation_error(self, client):
        r = await client.post("/v1/decisions/evaluate", json={"tenant_id": "t1"})
        assert r.status_code == 422

    @pytest.mark.asyncio
    async def test_evaluate_idempotency_header_required_when_configured(self, client, monkeypatch):
        from decision_api.config import settings

        monkeypatch.setattr(settings, "evaluate_require_idempotency_key", True)
        r = await client.post(
            "/v1/decisions/evaluate",
            json={"tenant_id": "t1", "event_type": "login", "entity_id": "u1", "payload": {}},
        )
        assert r.status_code == 422
        d = r.json()["detail"]
        assert d.get("error") == "evaluate_idempotency_required"

    @pytest.mark.asyncio
    async def test_evaluate_idempotency_header_satisfies_requirement(self, client, monkeypatch):
        from decision_api.config import settings

        monkeypatch.setattr(settings, "evaluate_require_idempotency_key", True)
        mock_session = AsyncMock()
        mock_session.add = MagicMock()
        mock_session.commit = AsyncMock()
        from decision_api.main import get_session

        with patch("decision_api.main.evaluate_json_rules", return_value=([], [], 0.0, [])):
            with patch("decision_api.main.evaluate_opa_or_raise", new_callable=AsyncMock, return_value=None):
                with patch("decision_api.main._fetch_ml_score_wrapped", new_callable=AsyncMock, return_value=(None, {})):
                    client.tarka_app.dependency_overrides[get_session] = _override_session_factory(mock_session)
                    r = await client.post(
                        "/v1/decisions/evaluate",
                        headers={"Idempotency-Key": "idem-eval-1"},
                        json={"tenant_id": "t1", "event_type": "login", "entity_id": "u1", "payload": {}},
                    )
                    client.tarka_app.dependency_overrides.pop(get_session, None)
        assert r.status_code == 200


class TestAdminReload:
    @pytest.mark.asyncio
    async def test_reload_rules(self, client):
        with patch("decision_api.main.load_rules"):
            r = await client.post("/v1/admin/rules/reload")
            assert r.status_code == 200


class TestOpsEndpoints:
    @pytest.mark.asyncio
    async def test_ops_governance_includes_calibration_status(self, client):
        r = await client.get("/v1/ops/governance")
        assert r.status_code == 200
        data = r.json()
        assert "calibration_status" in data
        assert "mobile_attestation_taxonomy" in data
        assert data["mobile_attestation_taxonomy"].get("attestation_schema_version") == 1

    @pytest.mark.asyncio
    async def test_ops_calibration_status(self, client):
        r = await client.get("/v1/ops/calibration-status", params={"tenant_id": "t1"})
        assert r.status_code == 200
        data = r.json()
        assert data["tenant_id"] == "t1"
        assert "calibration" in data


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


class TestChampionChallengerPolicyRouting:
    """OSS #31: optional audit-only challenger rule path vs production canary."""

    @pytest.mark.asyncio
    async def test_policy_routing_in_audit_when_enabled(self, client, monkeypatch):
        from decision_api.config import settings as cfg_settings

        monkeypatch.setattr(cfg_settings, "policy_champion_challenger_enabled", True)

        mock_session = AsyncMock()
        captured: list = []

        def _capture_add(obj):
            captured.append(obj)

        mock_session.add = MagicMock(side_effect=_capture_add)
        mock_session.commit = AsyncMock()
        from decision_api.main import get_session

        def _fake_eval(features, redis_tags, tenant_id, entity_id, evaluation_mode="production", signal_tags=None):
            if evaluation_mode == "challenger":
                return ([], [], 50.0, [])
            return ([], [], 0.0, [])

        with patch("decision_api.main.evaluate_json_rules", side_effect=_fake_eval):
            with patch("decision_api.main.evaluate_opa_or_raise", new_callable=AsyncMock, return_value=None):
                with patch("decision_api.main._fetch_ml_score_wrapped", new_callable=AsyncMock, return_value=(None, {})):
                    client.tarka_app.dependency_overrides[get_session] = _override_session_factory(mock_session)
                    r = await client.post(
                        "/v1/decisions/evaluate",
                        json={"tenant_id": "t1", "event_type": "login", "entity_id": "u1", "payload": {}},
                    )
                    client.tarka_app.dependency_overrides.pop(get_session, None)
        assert r.status_code == 200
        assert len(captured) == 1
        snap = captured[0].payload_snapshot
        assert "canary_cohort" in snap
        assert snap["canary_cohort"].get("cohort_sticky_id")
        assert "policy_routing" in snap
        pr = snap["policy_routing"]
        assert pr["champion_decision"] == "allow"
        assert pr["challenger_decision"] == "review"
        assert pr["decisions_agree"] is False
        assert "cohort_bucket_0_99" in pr


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
