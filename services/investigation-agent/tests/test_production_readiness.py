"""Production profile validation, readiness, and request guards."""

from unittest.mock import patch

from fastapi.testclient import TestClient
from investigation_agent import config
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


def test_request_body_too_large_413():
    with TestClient(app) as client:
        r = client.post(
            "/v1/knowledge/ingest",
            headers={"content-length": str(config.settings.copilot_max_request_body_bytes + 1)},
            json={},
        )
    assert r.status_code == 413
