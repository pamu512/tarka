from fraud_stack_sdk.client import InferenceContext


def test_python_inference_contract_has_core_fields() -> None:
    payload: InferenceContext = {
        "schema_version": "3",
        "calibration_profile": "default",
        "expected_calibration_version": 1,
        "integrity_confidence": 0.7,
        "tamper_risk": 0.1,
        "network_trust": 0.9,
        "replay_risk": 0.0,
        "geo_consistency_risk": 0.2,
        "top_signals": [],
        "confidence_tier": "medium",
        "driver_reasons": [],
        "colocation_risk": 0.0,
        "copresence_risk": 0.0,
        "impossible_travel_risk": 0.0,
        "velocity_events_5m": 0,
        "velocity_events_1h": 0,
        "velocity_events_24h": 0,
    }
    assert payload["schema_version"] == "3"
    assert payload["network_trust"] == 0.9
