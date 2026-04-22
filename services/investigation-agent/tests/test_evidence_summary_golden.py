from __future__ import annotations
import json
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from investigation_agent import main as main_mod
from investigation_agent.main import app

"""Golden fixtures for POST /v1/evidence/summary (OSS #40 — citations + next actions)."""
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "evidence_summary"


def _assert_dict_subset(sub: dict[str, Any], full: dict[str, Any]) -> None:
    for k, v in sub.items():
        assert k in full, f"missing key {k!r}"
        if isinstance(v, dict) and isinstance(full[k], dict):
            _assert_dict_subset(v, full[k])
        elif isinstance(v, list) and isinstance(full[k], list):
            assert len(full[k]) == len(v), f"list length mismatch for {k}"
            for exp_item, act_item in zip(v, full[k], strict=True):
                if isinstance(exp_item, dict) and isinstance(act_item, dict):
                    _assert_dict_subset(exp_item, act_item)
                else:
                    assert act_item == exp_item
        else:
            assert full[k] == v


@pytest.mark.parametrize(
    "name",
    [
        "case01_rule_typology_trace",
        "case02_typology_drivers",
        "case03_audit_anchors",
    ],
)
def test_evidence_summary_golden_fixtures(name: str) -> None:
    req = json.loads((FIXTURES / f"{name}.request.json").read_text())
    expected = json.loads((FIXTURES / f"{name}.expected.json").read_text())
    with TestClient(app) as client:
        r = client.post("/v1/evidence/summary", json=req)
        assert r.status_code == 200
        body = r.json()
        _assert_dict_subset(expected, body)
        r2 = client.post("/v1/evidence/summary", json=req)
        assert r2.json() == body


def test_evidence_summary_automated_action_requires_allowlist(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = {
        "tenant_id": "demo",
        "analyst_id": "analyst-1",
        "reply": "x",
        "claims": [{"text": "c", "source": "human"}],
        "proposed_next_actions": [
            {
                "id": "auto_escalate",
                "label": "Open escalation ticket",
                "kind": "automated_side_effect",
                "resolves_to": [{"artifact": "case", "id": "case-1"}],
            }
        ],
        "claims_deterministic_support": [],
        "turn_id": "golden-allowlist",
    }
    monkeypatch.setattr(main_mod.settings, "evidence_summary_automated_action_allowlist", "")
    with TestClient(app) as client:
        r = client.post("/v1/evidence/summary", json=payload)
    assert r.status_code == 200
    assert r.json().get("next_actions") == []

    monkeypatch.setattr(main_mod.settings, "evidence_summary_automated_action_allowlist", "auto_escalate,other")
    with TestClient(app) as client:
        r2 = client.post("/v1/evidence/summary", json=payload)
    assert r2.status_code == 200
    acts = r2.json().get("next_actions") or []
    assert len(acts) == 1
    assert acts[0]["id"] == "auto_escalate"
    assert acts[0]["kind"] == "automated_side_effect"
