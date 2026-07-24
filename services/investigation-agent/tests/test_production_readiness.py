"""Production profile validation, readiness, and request guards."""

from pathlib import Path
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


def test_ready_degraded_when_rag_unavailable_but_okf_healthy():
    with (
        patch("investigation_agent.main.runtime_readiness_errors", return_value=["rag down"]),
        patch("investigation_agent.main._okf_readiness_errors", return_value=[]),
        patch.object(config.settings, "okf_enabled", True),
        TestClient(app) as client,
    ):
        r = client.get("/v1/ready")
    assert r.status_code == 200
    assert r.json() == {"status": "degraded", "warnings": ["rag_unavailable"]}


def test_ready_degraded_when_okf_unavailable_but_rag_healthy():
    with (
        patch("investigation_agent.main.runtime_readiness_errors", return_value=[]),
        patch("investigation_agent.main._okf_readiness_errors", return_value=["okf down"]),
        patch.object(config.settings, "okf_enabled", True),
        TestClient(app) as client,
    ):
        response = client.get("/v1/ready")

    assert response.status_code == 200
    assert response.json() == {
        "status": "degraded",
        "warnings": ["okf_unavailable"],
    }


def test_ready_allows_disabled_okf_when_rag_is_healthy():
    with (
        patch("investigation_agent.main.runtime_readiness_errors", return_value=[]),
        patch("investigation_agent.main._okf_readiness_errors", return_value=[]),
        patch.object(config.settings, "okf_enabled", False),
        TestClient(app) as client,
    ):
        response = client.get("/v1/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ready"}


def test_ready_unhealthy_when_rag_and_okf_unavailable():
    with (
        patch("investigation_agent.main.runtime_readiness_errors", return_value=["rag down"]),
        patch("investigation_agent.main._okf_readiness_errors", return_value=["okf down"]),
        patch.object(config.settings, "okf_enabled", True),
        TestClient(app) as client,
    ):
        r = client.get("/v1/ready")
    assert r.status_code == 503
    assert r.json() == {
        "status": "not_ready",
        "errors": ["rag_unavailable", "okf_unavailable"],
    }


def test_ready_unhealthy_when_only_enabled_rag_is_unavailable():
    with (
        patch("investigation_agent.main.runtime_readiness_errors", return_value=["rag down"]),
        patch("investigation_agent.main._okf_readiness_errors", return_value=[]),
        patch.object(config.settings, "okf_enabled", False),
        TestClient(app) as client,
    ):
        response = client.get("/v1/ready")

    assert response.status_code == 503
    assert response.json() == {
        "status": "not_ready",
        "errors": ["rag_unavailable"],
    }


def test_health_exposes_only_stable_status_and_codes():
    with (
        patch(
            "investigation_agent.main.production_config_errors",
            return_value=["invalid database at /private/config"],
        ),
        patch(
            "investigation_agent.main._okf_readiness_errors",
            return_value=["invalid source at /private/knowledge"],
        ),
        TestClient(app) as client,
    ):
        response = client.get("/v1/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "warnings": ["production_config_invalid", "okf_unavailable"],
    }
    assert "/private/" not in response.text


def test_detailed_health_is_authenticated_admin_only(monkeypatch):
    monkeypatch.setenv("API_KEYS", "admin-key")
    monkeypatch.setenv("API_KEY_TENANT_MAP", '{"admin-key":["*"]}')
    monkeypatch.setenv("OKF_ADMIN_API_KEYS", "admin-key")
    main_mod._valid_api_keys = None
    try:
        with TestClient(app) as client:
            unauthenticated = client.get("/v1/admin/health/details")
            authenticated = client.get(
                "/v1/admin/health/details",
                headers={"x-api-key": "admin-key"},
            )
    finally:
        main_mod._valid_api_keys = None

    assert unauthenticated.status_code == 401
    assert authenticated.status_code == 200
    assert "production" in authenticated.json()


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


def test_unauthenticated_readiness_never_leaks_paths_or_raw_errors(monkeypatch):
    monkeypatch.setenv("API_KEYS", "secure-key")
    monkeypatch.setenv("API_KEY_TENANT_MAP", '{"secure-key":["t1"]}')
    monkeypatch.delenv("ALLOW_INSECURE_NO_AUTH", raising=False)
    main_mod._valid_api_keys = None
    secret_path = "/var/lib/tarka/private/tenant-a/source-manifest.json"
    try:
        with (
            patch(
                "investigation_agent.main.runtime_readiness_errors",
                return_value=[f"rag sqlite unavailable: {secret_path}"],
            ),
            patch(
                "investigation_agent.main._okf_readiness_errors",
                return_value=[f"invalid source hash at {secret_path}: expected deadbeef"],
            ),
            patch.object(config.settings, "okf_enabled", True),
            TestClient(app) as client,
        ):
            ready = client.get("/v1/ready")
            health = client.get("/v1/health")
    finally:
        main_mod._valid_api_keys = None

    assert ready.status_code == 503
    assert ready.json() == {
        "status": "not_ready",
        "errors": ["rag_unavailable", "okf_unavailable"],
    }
    public_payload = ready.text + health.text
    assert secret_path not in public_payload
    assert "deadbeef" not in public_payload
    assert "source hash" not in public_payload


def test_openapi_ready_contract_covers_graceful_knowledge_degradation():
    import yaml

    contract = yaml.safe_load(
        (
            Path(__file__).resolve().parents[3]
            / "contracts"
            / "openapi"
            / "investigation-agent.yaml"
        ).read_text(encoding="utf-8")
    )
    responses = contract["paths"]["/v1/ready"]["get"]["responses"]
    description = contract["paths"]["/v1/ready"]["get"]["description"].lower()
    ok_schema = responses["200"]["content"]["application/json"]["schema"]
    unavailable_schema = responses["503"]["content"]["application/json"]["schema"]

    assert set(ok_schema["properties"]["status"]["enum"]) == {"ready", "degraded"}
    assert set(ok_schema["properties"]["warnings"]["items"]["enum"]) == {
        "rag_unavailable",
        "okf_unavailable",
    }
    assert set(unavailable_schema["properties"]["errors"]["items"]["enum"]) == {
        "rag_unavailable",
        "okf_unavailable",
    }
    assert "rag" in description
    assert "okf" in description
    assert "disabled" in description
    assert "degraded" in description
    assert "all usable" in description


def test_request_body_too_large_413():
    with TestClient(app) as client:
        r = client.post(
            "/v1/knowledge/ingest",
            headers={"content-length": str(config.settings.copilot_max_request_body_bytes + 1)},
            json={},
        )
    assert r.status_code == 413
