"""Co-presence features from location/inference reach JSON rules (Wave A)."""

from __future__ import annotations

import json
from pathlib import Path

from decision_api.inference_build import build_inference_context
from decision_api.json_rules import evaluate_json_rules
from decision_api.rule_pack_validation import validate_rule_pack

_PACK_PATH = (
    Path(__file__).resolve().parents[1] / "rules" / "location_copresence_v1.json"
)


def test_location_copresence_pack_validates():
    data = json.loads(_PACK_PATH.read_text(encoding="utf-8"))
    assert data.get("mode") == "shadow"
    assert validate_rule_pack(data) == []


def test_copresence_risk_hits_example_rules():
    """Features merged from location_meta must fire the example pack rules."""
    import decision_api.json_rules as mod

    pack = json.loads(_PACK_PATH.read_text(encoding="utf-8"))
    pack["_source_file"] = "location_copresence_v1.json"
    # Evaluate as active for the unit contract (disk mode is shadow).
    pack["mode"] = "active"
    mod._cached_packs = [pack]

    ctx = build_inference_context(
        signal_tags=[],
        rule_hits=[],
        ml_score=10.0,
        final_score=10.0,
        features={"distinct_session_id_24h": 4},
        location_meta={
            "location_confidence": 0.7,
            "copresence_risk": 0.65,
            "impossible_travel_risk": 0.5,
            "geo_consistency_risk": 0.2,
        },
    )
    assert ctx["copresence_risk"] >= 0.5
    assert ctx["impossible_travel_risk"] >= 0.45

    features = {
        "copresence_risk": ctx["copresence_risk"],
        "impossible_travel_risk": ctx["impossible_travel_risk"],
        "colocation_risk": ctx["colocation_risk"],
    }
    hits, tags, delta, _ = evaluate_json_rules(features, [])
    assert "copresence_risk_elevated" in hits
    assert "impossible_travel_elevated" in hits
    assert "location:copresence_elevated" in tags
    assert "location:impossible_travel" in tags
    assert delta >= 18 + 22
