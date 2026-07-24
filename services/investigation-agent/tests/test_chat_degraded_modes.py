from __future__ import annotations

from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient
from investigation_agent import agent_run_store, config
from investigation_agent.main import app

"""Chat degraded mode contract: copilot_mode + degraded_reasons."""


def test_chat_returns_tools_only_deterministic_when_llm_key_missing(monkeypatch, tmp_path):
    payload = {
        "tenant_id": "demo",
        "analyst_id": "analyst-1",
        "messages": [{"role": "user", "content": "status?"}],
    }
    monkeypatch.setattr(config.settings, "openai_api_key", "")
    monkeypatch.setattr(config.settings, "case_api_url", "http://case.test")
    monkeypatch.setattr(config.settings, "decision_api_url", "")
    monkeypatch.setattr(config.settings, "graph_service_url", "")
    monkeypatch.setattr(config.settings, "copilot_plain_chat", False)
    monkeypatch.setattr(config.settings, "copilot_hide_tools_without_upstream", True)
    monkeypatch.setattr(config.settings, "copilot_disabled_tools", "")
    monkeypatch.setenv("INVESTIGATION_DATA_DIR", str(tmp_path))
    agent_run_store.reset_connection_for_tests()
    with patch("investigation_agent.main._execute_tool", new=AsyncMock(return_value={"items": []})):
        with TestClient(app) as client:
            r = client.post("/v1/chat", json=payload)
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["copilot_mode"] == "tools_only_deterministic"
    assert "openai_api_key_missing" in (out.get("degraded_reasons") or [])
    assert isinstance(out.get("tool_calls"), list)
    assert all(
        claim.get("source") != "tool" or claim.get("supporting_tool_call_indices")
        for claim in out.get("claims") or []
    )
    assert out["agent_run"]["model_provider"] == "deterministic"
    assert out["agent_run"]["prompt_hash"]
    persisted = agent_run_store.get_agent_run(
        tenant_id="demo",
        agent_run_id=out["agent_run"]["agent_run_id"],
    )
    assert persisted == out["agent_run"]
    agent_run_store.reset_connection_for_tests()


def test_chat_returns_read_only_summary_when_plain_chat_enabled(monkeypatch, tmp_path):
    payload = {
        "tenant_id": "demo",
        "analyst_id": "analyst-1",
        "messages": [{"role": "user", "content": "hello"}],
    }
    monkeypatch.setattr(config.settings, "openai_api_key", "test-key")
    monkeypatch.setattr(config.settings, "copilot_plain_chat", True)
    monkeypatch.setattr(config.settings, "copilot_hide_tools_without_upstream", True)
    monkeypatch.setattr(config.settings, "copilot_disabled_tools", "")
    monkeypatch.setattr(config.settings, "case_api_url", "http://case.test")
    monkeypatch.setattr(config.settings, "decision_api_url", "")
    monkeypatch.setattr(config.settings, "graph_service_url", "")
    monkeypatch.setenv("INVESTIGATION_DATA_DIR", str(tmp_path))
    agent_run_store.reset_connection_for_tests()
    with patch(
        "investigation_agent.main._llm_tool_loop",
        new=AsyncMock(return_value=("all good", [], {}, 1)),
    ):
        with TestClient(app) as client:
            r = client.post("/v1/chat", json=payload)
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["copilot_mode"] == "read_only_summary"
    assert "tool_surface_empty" in (out.get("degraded_reasons") or [])
    assert "copilot_plain_chat_enabled" in (out.get("degraded_reasons") or [])
    assert out["agent_run"]["model_provider"] == "openai_compatible"
    assert out["agent_run_persistence"] == "persisted"
    agent_run_store.reset_connection_for_tests()


def test_strict_refusal_persists_agent_run(monkeypatch, tmp_path):
    payload = {
        "tenant_id": "demo",
        "analyst_id": "analyst-1",
        "messages": [{"role": "user", "content": "Summarize the case"}],
    }
    monkeypatch.setattr(config.settings, "openai_api_key", "test-key")
    monkeypatch.setattr(config.settings, "copilot_plain_chat", False)
    monkeypatch.setattr(config.settings, "copilot_assurance_mode", "strict")
    monkeypatch.setattr(config.settings, "copilot_disabled_tools", "")
    monkeypatch.setattr(config.settings, "case_api_url", "http://case.test")
    monkeypatch.setattr(config.settings, "decision_api_url", "")
    monkeypatch.setattr(config.settings, "graph_service_url", "")
    monkeypatch.setenv("INVESTIGATION_DATA_DIR", str(tmp_path))
    agent_run_store.reset_connection_for_tests()
    raw = (
        "Everything succeeded.\n"
        'TARKA_CLAIMS_JSON={"claims":[{"text":"Everything succeeded.",'
        '"source":"unknown"}]}'
    )
    tool_calls = [
        {
            "tool": "get_case",
            "args": {"case_id": "c1"},
            "result": {"error": "upstream_unavailable"},
        }
    ]
    with patch(
        "investigation_agent.main._llm_tool_loop",
        new=AsyncMock(return_value=(raw, tool_calls, {}, 1)),
    ):
        with TestClient(app) as client:
            response = client.post("/v1/chat", json=payload)

    assert response.status_code == 200, response.text
    out = response.json()
    assert "withheld" in out["reply"].lower()
    assert out["agent_run"]["uncertainty"]["assurance_refused"] is True
    assert (
        agent_run_store.get_agent_run(
            tenant_id="demo",
            agent_run_id=out["agent_run"]["agent_run_id"],
        )
        == out["agent_run"]
    )
    agent_run_store.reset_connection_for_tests()
