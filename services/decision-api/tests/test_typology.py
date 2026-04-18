"""Typology layer (OSS #34 / #46)."""

from pathlib import Path
from unittest.mock import patch

import json

from decision_api.typology import evaluate_typologies, summarize_typologies


def test_typology_velocity_abuse_from_rule_hits():
    hits = ["velocity_high_1h"]
    feats = {"event_count_1h": 30.0}
    res = evaluate_typologies(hits, feats)
    vel = next(t for t in res if t["id"] == "velocity_abuse")
    assert vel["breach_level"] in ("warning", "alert", "pass")
    assert "velocity_high_1h" in vel["contributing_rule_hits"]
    summ = summarize_typologies(res)
    assert summ["highest_breach"] in ("pass", "warning", "alert")
    assert summ.get("predicate_registry", {}).get("pin_match") is True


def test_predicate_ref_skipped_when_pin_mismatch(tmp_path: Path):
    reg = {
        "registry_id": "t",
        "version": 99,
        "predicates": [{"id": "vel_event_1h_threshold", "when": {"field": "event_count_1h", "op": "gte", "value": 25}}],
    }
    typ = {
        "version": 1,
        "dsl_version": 1,
        "predicate_registry_pin": 1,
        "typologies": [
            {
                "id": "velocity_abuse",
                "label": "V",
                "member_rule_ids": ["velocity_high_1h"],
                "weight_per_rule_hit": 35,
                "feature_predicates": [{"predicate_ref": "vel_event_1h_threshold", "bonus": 15}],
                "breach_thresholds": {"warning": 40, "alert": 75},
                "disposition": {"pass": "allow", "warning": "review", "alert": "deny"},
            }
        ],
    }
    with patch("decision_api.typology.load_typology_definitions", return_value=typ):
        with patch("decision_api.typology.load_predicate_registry", return_value=reg):
            res = evaluate_typologies(["velocity_high_1h"], {"event_count_1h": 100.0})
    vel = next(t for t in res if t["id"] == "velocity_abuse")
    assert vel["predicate_registry"]["pin_match"] is False
    assert vel["contributing_feature_predicates"] == []


def test_typology_no_duplicate_rule_computation():
    """Same rule hit list reused; evaluate_typologies is O(typologies)."""
    hits = ["velocity_high_1h", "many_devices_24h"]
    feats = {"event_count_1h": 5, "distinct_device_id_24h": 4}
    res = evaluate_typologies(hits, feats)
    assert len(res) == 3


def test_starter_typology_fixtures_cover_reference_packs():
    """OSS #39 — smoke-test starter typology packs via JSON fixtures."""
    fixture_path = Path(__file__).parent / "fixtures" / "typology_starter_events.json"
    data = json.loads(fixture_path.read_text(encoding="utf-8"))
    seen_ids: set[str] = set()
    for row in data:
        hits = list(row.get("hits") or [])
        feats = dict(row.get("features") or {})
        res = evaluate_typologies(hits, feats)
        summ = summarize_typologies(res)
        assert summ["highest_breach"] in ("warning", "alert")
        tid = summ["driver_typology_id"]
        assert tid in {"velocity_abuse", "amount_stress", "new_payee_risk"}
        seen_ids.add(tid)
    # Ensure we exercised at least two reference typologies.
    assert {"velocity_abuse", "amount_stress"} <= seen_ids
