"""Production profile validation, readiness, and request guards."""

from unittest.mock import patch

from fastapi.testclient import TestClient
from investigation_agent import config
import investigation_agent.main as main_mod
from investigation_agent.main import app
from investigation_agent.production_config import production_config_errors, runtime_readiness_errors


def test_production_config_errors_empty_when_not_production():
    with patch.object(config.settings, "copilot_production_mode", False):
        assert production_config_errors(config.settings) == []


def test_production_config_errors_when_wildcard_analyst():
    with patch.object(config.settings, "copilot_production_mode", True):
        with patch.object(config.settings, "copilot_require_investigation_api_key", True):
            with patch.object(config.settings, "allowed_analysts", "*"):
                with patch.object(config.settings, "openai_api_key", "sk-test"):
                    errs = production_config_errors(config.settings, api_keys_raw="k1")
                    assert any("ALLOWED_ANALYSTS" in e for e in errs)


def test_runtime_readiness_errors_empty():
    errs = runtime_readiness_errors()
    assert isinstance(errs, list)


def test_runtime_readiness_errors_reports_rag_sql_probe_failure():
    with patch("investigation_agent.production_config.knowledge_store.rag_health_check") as probe:
        probe.return_value = (False, "sqlite unavailable")
        errs = runtime_readiness_errors()
    assert errs == ["rag sqlite unavailable: sqlite unavailable"]


def test_ready_degraded_when_rag_unavailable_but_okf_available():
    with (
        patch("investigation_agent.main.runtime_readiness_errors", return_value=["rag down"]),
        patch("investigation_agent.main._okf_readiness_errors", return_value=[]),
        patch.object(config.settings, "okf_enabled", True),
        TestClient(app) as client,
    ):
        r = client.get("/v1/ready")
    assert r.status_code == 200
    assert r.json()["status"] == "degraded"


def test_ready_unhealthy_when_rag_and_okf_unavailable():
    with (
        patch("investigation_agent.main.runtime_readiness_errors", return_value=["rag down"]),
        patch("investigation_agent.main._okf_readiness_errors", return_value=["okf down"]),
        patch.object(config.settings, "okf_enabled", True),
        TestClient(app) as client,
    ):
        r = client.get("/v1/ready")
    assert r.status_code == 503
    assert r.json()["status"] == "not_ready"


def test_health_includes_production_block():
    with TestClient(app) as client:
        r = client.get("/v1/health")
    assert r.status_code == 200
    prod = r.json().get("production") or {}
    assert "mode" in prod
    assert "config_ok" in prod
    assert "max_request_body_bytes" in prod


def test_ready_endpoint():
    with TestClient(app) as client:
        r = client.get("/v1/ready")
    assert r.status_code == 200
    assert r.json().get("status") == "ready"


def test_health_probes_bypass_api_key_but_data_routes_remain_protected(monkeypatch):
    monkeypatch.setenv("API_KEYS", "secure-key")
    monkeypatch.setenv("API_KEY_TENANT_MAP", '{"secure-key":["t1"]}')
    monkeypatch.delenv("ALLOW_INSECURE_NO_AUTH", raising=False)
    main_mod._valid_api_keys = None
    try:
        with (
            patch("investigation_agent.main.runtime_readiness_errors", return_value=[]),
            patch("investigation_agent.main._okf_readiness_errors", return_value=[]),
            TestClient(app) as client,
        ):
            assert client.get("/v1/health").status_code == 200
            assert client.get("/v1/ready").status_code == 200
            protected = client.post(
                "/v1/chat",
                json={
                    "tenant_id": "t1",
                    "analyst_id": "a1",
                    "messages": [{"role": "user", "content": "hello"}],
                },
            )
        assert protected.status_code == 401
    finally:
        main_mod._valid_api_keys = None


def test_request_body_too_large_413():
    with TestClient(app) as client:
        r = client.post(
            "/v1/knowledge/ingest",
            headers={"content-length": str(config.settings.copilot_max_request_body_bytes + 1)},
            json={},
        )
    assert r.status_code == 413
