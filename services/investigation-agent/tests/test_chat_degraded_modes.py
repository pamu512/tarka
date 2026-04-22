from __future__ import annotations

from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient
from investigation_agent import config
from investigation_agent.main import app

"""Chat degraded mode contract: copilot_mode + degraded_reasons."""

def test_chat_returns_tools_only_deterministic_when_llm_key_missing(monkeypatch):
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
    with patch("investigation_agent.main._execute_tool", new=AsyncMock(return_value={"items": []})):
        with TestClient(app) as client:
            r = client.post("/v1/chat", json=payload)
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["copilot_mode"] == "tools_only_deterministic"
    assert "openai_api_key_missing" in (out.get("degraded_reasons") or [])
    assert isinstance(out.get("tool_calls"), list)


def test_chat_returns_read_only_summary_when_plain_chat_enabled(monkeypatch):
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
    with patch("investigation_agent.main._llm_tool_loop", new=AsyncMock(return_value=("all good", [], {}, 1))):
        with TestClient(app) as client:
            r = client.post("/v1/chat", json=payload)
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["copilot_mode"] == "read_only_summary"
    assert "tool_surface_empty" in (out.get("degraded_reasons") or [])
    assert "copilot_plain_chat_enabled" in (out.get("degraded_reasons") or [])
