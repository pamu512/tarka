"""Inference context enrichment from first-class calibration/location services.

Counters no longer flow through a dedicated hop: the local AggregateStore
(services/shared/fraud_aggregates.py) owns aggregates and they reach the
inference context via ``features`` (source "aggregate-store": the local AggregateStore owns counters).
"""

from decision_api.inference_build import build_inference_context


def test_build_inference_context_applies_service_metadata():
    ctx = build_inference_context(
        signal_tags=["sdk:vpn"],
        rule_hits=["velocity_high_1h"],
        ml_score=72.0,
        final_score=81.0,
        features={"event_count_5m": 7, "event_count_1h": 22, "event_count_24h": 101},
        calibration_meta={
            "profile_id": "payments_strict",
            "profile_version": 4,
            "expected_calibration_version": 9,
            "calibrated_confidence": 0.73,
        },
        location_meta={
            "location_confidence": 0.64,
            "copresence_risk": 0.41,
            "impossible_travel_risk": 0.28,
            "geo_consistency_risk": 0.33,
        },
    )

    assert ctx["calibration_profile"] == "payments_strict"
    assert ctx["calibration_profile_version"] == 4
    assert ctx["expected_calibration_version"] == 9
    assert ctx["location_confidence"] == 0.64
    assert ctx["confidence_sources"]["calibration"] == "service"
    assert ctx["confidence_sources"]["counter"] == "aggregate-store"
    assert ctx["confidence_sources"]["location"] == "service"
    assert ctx["velocity_events_5m"] == 7
    assert ctx["velocity_events_1h"] == 22
    assert ctx["velocity_events_24h"] == 101
