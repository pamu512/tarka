"""Reference deployment: /v1/setup, turn bundle, turn_metrics shape."""

import json
from pathlib import Path

from fastapi.testclient import TestClient
from investigation_agent.main import app


def test_setup_endpoint_shape():
    with TestClient(app) as client:
        r = client.get("/v1/setup")
    assert r.status_code == 200
    data = r.json()
    assert data.get("schema") == "saarthi_setup_v1"
    assert "checklist" in data
    assert "llm" in data and "embeddings" in data
    ids = {c.get("id") for c in data.get("checklist") or []}
    assert "llm_api_key" in ids


def test_turn_bundle_export():
    body = {
        "tenant_id": "demo",
        "analyst_id": "a1",
        "title": "Review",
        "turn_id": "550e8400-e29b-41d4-a716-446655440000",
        "reply": "Next: verify velocity.",
        "answer_sections": {"NEXT STEPS": "Pull audit"},
        "claims": [{"text": "Need audit", "source": "unknown"}],
        "tool_calls": [{"tool": "get_case", "args": {}, "result": {"ok": True}}],
    }
    with TestClient(app) as client:
        r = client.post("/v1/reports/turn-bundle", json=body)
    assert r.status_code == 200
    out = r.json()
    assert out.get("format") == "turn_bundle_v1"
    assert "NEXT STEPS" in (out.get("markdown") or "")
    assert out.get("structured", {}).get("tenant_id") == "demo"


def test_golden_prompts_pack_exists():
    root = Path(__file__).resolve().parents[1] / "src" / "investigation_agent" / "resources" / "golden_prompts_v1.json"
    data = json.loads(root.read_text(encoding="utf-8"))
    assert data.get("schema") == "saarthi_golden_prompts_v1"
    assert len(data.get("prompts") or []) >= 1
