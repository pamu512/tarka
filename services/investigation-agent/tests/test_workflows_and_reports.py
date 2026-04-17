"""Workflow manifests and case-summary PDF report."""

from fastapi.testclient import TestClient
from investigation_agent.main import app


def test_list_workflows():
    with TestClient(app) as client:
        r = client.get("/v1/workflows")
    assert r.status_code == 200
    data = r.json()
    assert "workflows" in data
    ids = {w["id"] for w in data["workflows"]}
    assert "sop_case_summary_v1" in ids


def test_chat_accepts_workflow_id():
    payload = {
        "tenant_id": "demo",
        "analyst_id": "a1",
        "workflow_id": "sop_case_summary_v1",
        "workflow_params": {"audience": "executive", "report_label": "Q4 review"},
        "messages": [{"role": "user", "content": "Summarize the case."}],
    }
    with TestClient(app) as client:
        r = client.post("/v1/chat", json=payload)
    assert r.status_code == 200
    body = r.json()
    assert body.get("workflow_id") == "sop_case_summary_v1"
    assert body.get("workflow_params", {}).get("audience") == "executive"


def test_chat_rejects_unknown_workflow():
    payload = {
        "tenant_id": "demo",
        "analyst_id": "a1",
        "workflow_id": "no_such_workflow",
        "messages": [{"role": "user", "content": "hi"}],
    }
    with TestClient(app) as client:
        r = client.post("/v1/chat", json=payload)
    assert r.status_code == 400


def test_case_summary_pdf_bytes():
    body = {
        "tenant_id": "demo",
        "analyst_id": "a1",
        "title": "Test summary",
        "turn_id": "550e8400-e29b-41d4-a716-446655440000",
        "case_id": "case-1",
        "workflow_id": "sop_case_summary_v1",
        "prompt_version": "3.2.0",
        "reply": "Executive overview text.",
        "answer_sections": {
            "facts_from_tools": "Entity X seen in audit.",
            "inferences": "Possible ATO.",
            "next_steps": "Pull velocity.",
        },
        "claims": [{"text": "Audit returned tier 2", "source": "tool"}],
    }
    with TestClient(app) as client:
        r = client.post("/v1/reports/case-summary", json=body)
    assert r.status_code == 200
    assert r.headers.get("content-type", "").startswith("application/pdf")
    assert r.content[:4] == b"%PDF"
