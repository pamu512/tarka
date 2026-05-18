"""Gate: POST /v1/ai/feedback appends a JSON line to the configured JSONL sink."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from starlette.testclient import TestClient

_SRC_ORCH = Path(__file__).resolve().parents[1] / "src"
_SRC_INGESTOR = Path(__file__).resolve().parents[2] / "ingestor" / "src"
for _p in (_SRC_ORCH, _SRC_INGESTOR):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from orchestrator.main import create_app  # noqa: E402


def test_post_ai_feedback_updates_jsonl(tmp_path: Path) -> None:
    jsonl = tmp_path / "rejections.jsonl"
    app = create_app(
        rule_engine_url="http://rules.test",
        shadow_agent_url=None,
        ai_feedback_jsonl=str(jsonl),
    )
    assert not jsonl.exists()
    payload = {
        "rejection_reasons": ["Hallucinated merchant name", "Contradicts ledger"],
        "tenant_id": "demo",
        "trace_id": "tr-gate-001",
        "source": "pytest",
        "context": "Analyst rejected Shadow narrative.",
    }
    with TestClient(app) as client:
        r = client.post("/v1/ai/feedback", json=payload)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert body["jsonl_path"] == str(jsonl.resolve())
    assert body["feedback_id"]

    lines = jsonl.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    row = json.loads(lines[0])
    assert row["schema"] == "tarka.ai_feedback.v1"
    assert row["feedback_id"] == body["feedback_id"]
    assert row["rejection_reasons"] == payload["rejection_reasons"]
    assert row["tenant_id"] == "demo"
    assert row["trace_id"] == "tr-gate-001"
    assert row["source"] == "pytest"


def test_post_ai_feedback_requires_at_least_one_reason(tmp_path: Path) -> None:
    jsonl = tmp_path / "empty.jsonl"
    app = create_app(
        rule_engine_url="http://rules.test",
        shadow_agent_url=None,
        ai_feedback_jsonl=str(jsonl),
    )
    with TestClient(app) as client:
        r = client.post("/v1/ai/feedback", json={"rejection_reasons": []})
    assert r.status_code == 422
    assert not jsonl.exists()
