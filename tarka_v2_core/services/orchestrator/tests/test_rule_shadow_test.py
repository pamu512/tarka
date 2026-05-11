"""Gate: shadow-test endpoint surfaces high hit-rate warnings for overly broad predicates."""

from __future__ import annotations

import sys
from pathlib import Path

from starlette.testclient import TestClient

_SRC_ORCH = Path(__file__).resolve().parents[1] / "src"
_SRC_INGESTOR = Path(__file__).resolve().parents[2] / "ingestor" / "src"
_SRC_RULE = Path(__file__).resolve().parents[2] / "rule_engine" / "src"
_SRC_SHARED = Path(__file__).resolve().parents[2] / "shared"
for _p in (_SRC_ORCH, _SRC_INGESTOR, _SRC_RULE, _SRC_SHARED):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from orchestrator.main import create_app  # noqa: E402


def test_shadow_test_amount_gt_one_warns_high_positive_rate() -> None:
    app = create_app(rule_engine_url="http://rules.test", shadow_agent_url=None)
    body = {
        "root_node": {
            "field": {"field": "amount"},
            "operator": "GT",
            "value": 1,
        },
        "action": "BLOCK",
    }
    with TestClient(app) as client:
        r = client.post("/v1/rules/shadow-test", json=body)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["sample_size"] == 1000
    assert data["matched_count"] == 980
    assert data["would_block_pct"] == 98.0
    assert data["would_flag_count"] == 0
    assert "blocked 98.0%" in data["summary_line"]
    assert data["warning"] == "HIGH POSITIVE RATE: This rule affects 98% of your traffic."


def test_shadow_test_flag_action_counts_flags_not_block_pct() -> None:
    app = create_app(rule_engine_url="http://rules.test", shadow_agent_url=None)
    body = {
        "root_node": {
            "field": {"field": "amount"},
            "operator": "GT",
            "value": 1,
        },
        "action": "FLAG",
    }
    with TestClient(app) as client:
        r = client.post("/v1/rules/shadow-test", json=body)
    assert r.status_code == 200
    data = r.json()
    assert data["would_block_pct"] == 0.0
    assert data["would_flag_count"] == 980
    assert data["warning"] is not None
