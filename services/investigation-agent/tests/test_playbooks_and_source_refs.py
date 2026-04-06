"""Playbooks API and source reference cards."""

from fastapi.testclient import TestClient
from investigation_agent.copilot_hardening import build_source_reference_cards, collect_grounding_tokens
from investigation_agent.main import app


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
