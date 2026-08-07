"""P1-typ: weighted typology aggregation telemetry."""

from __future__ import annotations

from decision_api.typology import weighted_aggregation_telemetry


def test_weighted_telemetry_has_configured_weights():
    out = weighted_aggregation_telemetry()
    assert out["schema_id"] == "tarka.typology_weighted_telemetry/v1"
    assert out["typology_count"] >= 1
    assert isinstance(out["configured"], list)
    row = out["configured"][0]
    assert "weight_per_rule_hit" in row
    assert "breach_thresholds" in row
    assert out["aggregation"]["mode"] == "max_breach_then_score"
