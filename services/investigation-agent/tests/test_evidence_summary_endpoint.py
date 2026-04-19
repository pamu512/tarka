from __future__ import annotations

from fastapi.testclient import TestClient
from investigation_agent.main import app


def _payload() -> dict:
    return {
        "tenant_id": "demo",
        "analyst_id": "analyst-1",
        "case_id": "case-123",
        "trace_id": "12345678-1234-5678-9012-123456789abc",
        "reply": "Risk indicators suggest review.",
        "claims": [
            {"text": "Trace 12345678-1234-5678-9012-123456789abc score is elevated", "source": "tool"},
            {"text": "Graph has shared-device linkage", "source": "tool"},
        ],
        "source_refs": [
            {
                "tool": "get_decision_audit",
                "ok": True,
                "trace_id": "12345678-1234-5678-9012-123456789abc",
            },
            {"tool": "subgraph", "ok": True, "case_id": "case-123", "entity_id": "user_1"},
        ],
        "claims_deterministic_support": [
            {"claim_index": 0, "supported": True, "method": "token_overlap", "hint": ["12345678-1234-5678-9012-123456789abc"]},
            {"claim_index": 1, "supported": False, "method": "token_overlap", "hint": []},
        ],
        "turn_id": "turn-fixed-1",
        "prompt_version": "3.2.0",
        "persona": "investigation",
    }


def test_evidence_summary_endpoint_deterministic():
    with TestClient(app) as client:
        p = _payload()
        r1 = client.post("/v1/evidence/summary", json=p)
        r2 = client.post("/v1/evidence/summary", json=p)

    assert r1.status_code == 200
    assert r2.status_code == 200
    b1 = r1.json()
    b2 = r2.json()
    assert b1 == b2
    assert isinstance(b1.get("summary"), str) and b1["summary"]
    assert b1.get("confidence_label") in {"low", "medium", "high"}
    assert b1["turn_id"] == "turn-fixed-1"
    citations = b1.get("citations") or []
    assert len(citations) >= 2
    assert any("12345678-1234-5678-9012-123456789abc" in str(c.get("text", "")) for c in citations)


def test_evidence_summary_deterministic_and_cited():
    payload = _payload()
    with TestClient(app) as client:
        r1 = client.post("/v1/evidence/summary", json=payload)
        r2 = client.post("/v1/evidence/summary", json=payload)
    assert r1.status_code == 200
    assert r2.status_code == 200
    b1 = r1.json()
    b2 = r2.json()
    assert b1 == b2
    assert b1["trace_id"] == payload["trace_id"]
    assert b1["claim_confidence_summary"]["high"] >= 1
    assert b1["claim_confidence_summary"]["medium"] >= 1
    assert len(b1["citations"]) >= 2
    assert b1["summary"] == payload["reply"]
    assert any(c.get("text", "").find(payload["trace_id"]) >= 0 and c.get("source") == "tool" for c in b1["citations"])
