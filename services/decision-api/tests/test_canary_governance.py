from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from decision_api.json_rules import evaluate_json_rules, governance_summary, load_rules

"""Canary / effective_at gating and governance summary."""

def test_challenger_mode_includes_canary_excluded_packs():
    """OSS #31: challenger path evaluates all packs that pass effective_at (ignores canary_percent)."""
    pack = {
        "version": 1,
        "_source_file": "test.json",
        "name": "t",
        "canary_percent": 0,
        "rules": [{"id": "always", "when": [{"field": "amount", "op": "gte", "value": 1}], "tags": ["x"], "score_delta": 5}],
        "tag_rules": [],
    }
    import decision_api.json_rules as jr

    jr._cached_packs = [pack]
    h, _, d, _pf = evaluate_json_rules({"amount": 100}, [], "t1", "e1", evaluation_mode="production")
    assert h == [] and d == 0.0
    h2, _, d2, _pf2 = evaluate_json_rules({"amount": 100}, [], "t1", "e1", evaluation_mode="challenger")
    assert "always" in h2 and d2 == 5.0


def test_simulation_bypasses_canary():
    pack = {
        "version": 1,
        "_source_file": "test.json",
        "name": "t",
        "canary_percent": 0,
        "rules": [{"id": "always", "when": [{"field": "amount", "op": "gte", "value": 1}], "tags": ["x"], "score_delta": 5}],
        "tag_rules": [],
    }
    import decision_api.json_rules as jr

    jr._cached_packs = [pack]
    h, t, d, _pfa = evaluate_json_rules({"amount": 100}, [], "t1", "e1", evaluation_mode="production")
    assert h == [] and d == 0.0
    h2, t2, d2, _pfb = evaluate_json_rules({"amount": 100}, [], "t1", "e1", evaluation_mode="simulation")
    assert "always" in h2 and d2 == 5.0


def test_effective_at_future_excludes_pack():
    future = (datetime.now(timezone.utc) + timedelta(days=7)).isoformat()
    pack = {
        "version": 1,
        "_source_file": "f.json",
        "effective_at": future,
        "rules": [{"id": "late", "when": [{"field": "amount", "op": "gte", "value": 1}], "tags": ["y"], "score_delta": 3}],
        "tag_rules": [],
    }
    import decision_api.json_rules as jr

    jr._cached_packs = [pack]
    h, _, d, _pfc = evaluate_json_rules({"amount": 50}, [], "t", "e", evaluation_mode="production")
    assert h == [] and d == 0.0


def test_governance_summary_shape():
    pack = {
        "version": 1,
        "_source_file": "g.json",
        "name": "g",
        "canary_percent": 25.0,
        "approved_by": "ops",
        "rules": [],
        "tag_rules": [],
    }
    import decision_api.json_rules as jr

    jr._cached_packs = [pack]
    jr._shadow_mode_packs = []
    g = governance_summary()
    assert g["active_pack_count"] == 1
    assert g["packs"][0]["canary_percent"] == 25.0
    assert g["packs"][0]["approved_by"] == "ops"


def test_load_rules_sets_source_file(tmp_path):
    p = tmp_path / "p.json"
    p.write_text(
        '{"version":1,"name":"x","rules":[{"id":"r","when":[{"field":"x","op":"gte","value":0}],"tags":["t"],"score_delta":1}],"tag_rules":[]}',
        encoding="utf-8",
    )
    with patch("decision_api.json_rules.settings") as mock:
        mock.rules_path = str(tmp_path)
        load_rules()
        from decision_api.json_rules import _cached_packs

        assert _cached_packs[0].get("_source_file") == "p.json"
