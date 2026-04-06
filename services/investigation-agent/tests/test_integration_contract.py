"""Integration contract snapshot (adapter parity, /v1/integration)."""

from fastapi.testclient import TestClient
from investigation_agent import config
from investigation_agent.integration_contract import (
    INTEGRATION_CONTRACT_VERSION,
    build_integration_snapshot,
    effective_disabled_tools,
    runtime_suppressed_tools,
)
from investigation_agent.main import app


def test_build_integration_snapshot_shape():
    snap = build_integration_snapshot(
        config.settings,
        disabled_tools=effective_disabled_tools(config.settings),
    )
    assert snap["contract_version"] == INTEGRATION_CONTRACT_VERSION
    assert "profile_id" in snap
    assert set(snap["upstream_configured"].keys()) == {"case_api", "decision_api", "graph_service"}
    assert snap["tools"]["enabled_count"] >= 1
    assert "get_case" in snap["tools"]["enabled"]
    assert "disabled_effective" in snap["tools"]
    assert "upstream_suppressed" in snap["tools"]


def test_disabled_tools_omit_from_enabled(monkeypatch):
    monkeypatch.setattr(config.settings, "copilot_hide_tools_without_upstream", False)
    snap = build_integration_snapshot(
        config.settings,
        disabled_tools=frozenset(["get_case", "list_cases"]),
    )
    enabled = snap["tools"]["enabled"]
    assert "get_case" not in enabled
    assert "list_cases" not in enabled


def test_runtime_suppresses_graph_when_unconfigured(monkeypatch):
    monkeypatch.setattr(config.settings, "copilot_hide_tools_without_upstream", True)
    monkeypatch.setattr(config.settings, "graph_service_url", "")
    sup = runtime_suppressed_tools(config.settings)
    assert "subgraph" in sup
    assert "subgraph_with_velocity" in sup
    eff = effective_disabled_tools(config.settings)
    snap = build_integration_snapshot(config.settings, disabled_tools=eff)
    assert "subgraph" not in snap["tools"]["enabled"]


def test_hide_upstream_can_be_disabled(monkeypatch):
    monkeypatch.setattr(config.settings, "copilot_hide_tools_without_upstream", False)
    monkeypatch.setattr(config.settings, "graph_service_url", "")
    assert runtime_suppressed_tools(config.settings) == frozenset()
    eff = effective_disabled_tools(config.settings)
    snap = build_integration_snapshot(config.settings, disabled_tools=eff)
    assert "subgraph" in snap["tools"]["enabled"]


def test_health_includes_integration():
    c = TestClient(app)
    r = c.get("/v1/health")
    assert r.status_code == 200
    data = r.json()
    assert "integration" in data
    assert data["integration"]["contract_version"] == INTEGRATION_CONTRACT_VERSION
    cf = data.get("copilot_features") or {}
    assert cf.get("evidence_bundle_format") == "dual"
    assert cf.get("evidence_bundle_v1") is True


def test_integration_endpoint():
    c = TestClient(app)
    r = c.get("/v1/integration")
    assert r.status_code == 200
    data = r.json()
    assert data["contract_version"] == INTEGRATION_CONTRACT_VERSION
    assert "families_enabled" in data
