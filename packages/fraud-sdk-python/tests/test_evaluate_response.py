"""Strict evaluate response parsing."""

import pytest
from fraud_stack_sdk.evaluate_response import (
    EvaluateResponseValidationError,
    parse_evaluate_response,
)


def _minimal_evaluate_json() -> dict:
    return {
        "trace_id": "550e8400-e29b-41d4-a716-446655440000",
        "decision": "allow",
        "score": 12.5,
        "tags": ["a"],
        "inference_context": {
            "schema_version": "3",
            "calibration_profile": "default",
            "expected_calibration_version": 1,
            "integrity_confidence": 0.5,
            "tamper_risk": 0.0,
            "network_trust": 0.8,
            "replay_risk": 0.0,
            "geo_consistency_risk": 0.0,
            "top_signals": [],
            "confidence_tier": "medium",
            "driver_reasons": [],
            "colocation_risk": 0.0,
            "copresence_risk": 0.0,
            "impossible_travel_risk": 0.0,
            "velocity_events_5m": 0,
            "velocity_events_1h": 0,
            "velocity_events_24h": 0,
        },
    }


def test_parse_evaluate_response_ok():
    out = parse_evaluate_response(_minimal_evaluate_json())
    assert out["decision"] == "allow"
    assert out["inference_context"]["schema_version"] == "3"


def test_parse_accepts_optional_graph_decision_explanation():
    body = _minimal_evaluate_json()
    body["graph_decision_explanation"] = {"schema_id": "tarka.graph_decision_explanation/v1", "factors": []}
    out = parse_evaluate_response(body)
    assert out["graph_decision_explanation"]["schema_id"] == "tarka.graph_decision_explanation/v1"


def test_parse_rejects_bad_decision():
    bad = _minimal_evaluate_json()
    bad["decision"] = "maybe"
    with pytest.raises(EvaluateResponseValidationError):
        parse_evaluate_response(bad)


def test_parse_rejects_score_range():
    bad = _minimal_evaluate_json()
    bad["score"] = 101
    with pytest.raises(EvaluateResponseValidationError):
        parse_evaluate_response(bad)
