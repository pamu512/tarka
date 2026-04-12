"""Playbooks API and source reference cards."""

from fastapi.testclient import TestClient
from investigation_agent.copilot_hardening import build_source_reference_cards, collect_grounding_tokens
from investigation_agent.main import app
from investigation_agent.personas import build_copilot_system_prompt, list_personas
from investigation_agent.playbooks import playbooks_catalog_fingerprint


def test_personas_catalog_and_prompts():
    ps = list_personas()
    assert len(ps) == 2
    ids = {p["id"] for p in ps}
    assert ids == {"investigation", "orchestrator"}
    assert "ORCHESTRATOR PRIORITIES" not in build_copilot_system_prompt("investigation")
    assert "ORCHESTRATOR PRIORITIES" in build_copilot_system_prompt("orchestrator")
    assert "workflow orchestrator" in build_copilot_system_prompt("orchestrator").lower()


def test_list_personas_http():
    with TestClient(app) as client:
        r = client.get("/v1/personas")
    assert r.status_code == 200
    data = r.json()
    assert len(data["personas"]) == 2


def test_chat_echoes_persona():
    payload = {
        "tenant_id": "demo",
        "analyst_id": "analyst-1",
        "persona": "orchestrator",
        "messages": [{"role": "user", "content": "hi"}],
    }
    with TestClient(app) as client:
        r = client.post("/v1/chat", json=payload)
    assert r.status_code == 200
    assert r.json().get("persona") == "orchestrator"


def test_playbooks_catalog_fingerprint_stable():
    a = playbooks_catalog_fingerprint()
    b = playbooks_catalog_fingerprint()
    assert a == b
    assert len(a) == 16
    assert all(c in "0123456789abcdef" for c in a)


def test_health_includes_playbooks_fingerprint():
    with TestClient(app) as client:
        r = client.get("/v1/health")
    assert r.status_code == 200
    fp = r.json()["copilot_features"]["playbooks_fingerprint"]
    assert fp == playbooks_catalog_fingerprint()


def test_chat_rejects_too_many_messages(monkeypatch):
    from investigation_agent import config

    monkeypatch.setattr(config.settings, "copilot_max_chat_messages", 2)
    payload = {
        "tenant_id": "demo",
        "analyst_id": "analyst-1",
        "messages": [
            {"role": "user", "content": "a"},
            {"role": "assistant", "content": "b"},
            {"role": "user", "content": "c"},
        ],
    }
    with TestClient(app) as client:
        r = client.post("/v1/chat", json=payload)
    assert r.status_code == 400


def test_list_playbooks():
    with TestClient(app) as client:
        r = client.get("/v1/playbooks")
    assert r.status_code == 200
    data = r.json()
    assert "playbooks" in data
    ids = {p["id"] for p in data["playbooks"]}
    assert "payments_first_party" in ids
    assert "account_takeover" in ids


def test_chat_rejects_bad_playbook():
    payload = {
        "tenant_id": "demo",
        "analyst_id": "analyst-1",
        "playbook_id": "nope_not_a_playbook",
        "messages": [{"role": "user", "content": "hi"}],
    }
    with TestClient(app) as client:
        r = client.post("/v1/chat", json=payload)
    assert r.status_code == 400


def test_source_refs_shape():
    tcs = [
        {
            "tool": "get_case",
            "args": {"case_id": "abc-123"},
            "result": {"case": {"id": "abc-123", "entity_id": "e1"}},
        },
        {"tool": "get_decision_audit", "args": {"trace_id": "12345678-1234-5678-9012-123456789abc"}, "result": {"error": "not_found"}},
    ]
    cards = build_source_reference_cards(tcs)
    assert len(cards) == 2
    assert cards[0]["tool"] == "get_case"
    assert cards[0]["ok"] is True
    assert cards[0]["case_id"] == "abc-123"
    assert cards[1]["ok"] is False


def test_grounding_includes_nested_entity_id():
    tcs = [
        {
            "tool": "get_case",
            "args": {},
            "result": {"case": {"id": "c1", "entity_id": "fraud_frank", "trace_id": "12345678-1234-5678-9012-123456789def"}},
        }
    ]
    g = collect_grounding_tokens(tcs)
    assert "fraud_frank" in g
    assert "12345678-1234-5678-9012-123456789def" in g
