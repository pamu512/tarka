import os

import pytest

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")

from decision_api.main import _graph_routing_match_when, decide_graph_routing  # noqa: E402


class TestGraphRoutingMatchWhen:
    def test_empty_when_always_true(self):
        assert _graph_routing_match_when([], {"event_type": "login", "base_score": 10})
        assert _graph_routing_match_when(None, {"event_type": "login", "base_score": 10})

    def test_string_equality(self):
        when = [{"op": "eq", "field": "event_type", "value": "login"}]
        assert _graph_routing_match_when(when, {"event_type": "login"})
        assert not _graph_routing_match_when(when, {"event_type": "payment"})

    def test_numeric_operators(self):
        ctx = {"base_score": 30}
        assert _graph_routing_match_when([{"op": "lt", "field": "base_score", "value": 40}], ctx)
        assert not _graph_routing_match_when([{"op": "lt", "field": "base_score", "value": 10}], ctx)
        assert _graph_routing_match_when([{"op": "gte", "field": "base_score", "value": 30}], ctx)
        assert not _graph_routing_match_when([{"op": "gt", "field": "base_score", "value": 30}], ctx)


class TestDecideGraphRouting:
    def test_policy_applied_for_login_low_risk(self, monkeypatch):
        from decision_api import main as m

        # Force a small in-memory policy to avoid disk I/O assumptions.
        policy = {
            "default": {"skip_graph": False, "graph_checkpoint": "standard"},
            "rules": [
                {
                    "id": "low_risk_login_skip",
                    "when": [
                        {"op": "eq", "field": "event_type", "value": "login"},
                        {"op": "lt", "field": "base_score", "value": 25},
                    ],
                    "skip_graph": True,
                    "graph_checkpoint": None,
                }
            ],
        }
        monkeypatch.setattr(m, "_graph_routing_policy", policy)

        out = decide_graph_routing("login", 10.0, tags=["sdk:bot"])
        assert out is not None
        assert out["skip_graph"] is True
        assert out["graph_checkpoint"] is None
        assert out["matched_rule_id"] == "low_risk_login_skip"

    def test_policy_default_used_when_no_rule_matches(self, monkeypatch):
        from decision_api import main as m

        policy = {
            "default": {"skip_graph": False, "graph_checkpoint": "standard"},
            "rules": [],
        }
        monkeypatch.setattr(m, "_graph_routing_policy", policy)

        out = decide_graph_routing("payment", 5.0, tags=[])
        assert out is not None
        assert out["skip_graph"] is False
        assert out["graph_checkpoint"] == "standard"
        assert out["matched_rule_id"] is None

