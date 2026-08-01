"""Sync enforcement_action on evaluate path (Wave A)."""

from decision_api.enforcement import (
    is_step_up_recommended,
    resolve_enforcement_action,
)
from decision_api.schemas import EvaluateResponse


def test_resolve_enforcement_sync_verbs():
    assert resolve_enforcement_action("deny", None) == "block"
    assert resolve_enforcement_action("deny", "allow") == "block"
    assert resolve_enforcement_action("allow", "step_up_mfa") == "step_up"
    assert resolve_enforcement_action("review", "step-up-attestation") == "step_up"
    assert resolve_enforcement_action("allow", None) == "allow"


def test_is_step_up_aliases_aligned():
    assert is_step_up_recommended("step_up_mfa")
    assert is_step_up_recommended("step-up-attestation")
    assert is_step_up_recommended("challenge")
    assert not is_step_up_recommended("manual_review")
    assert not is_step_up_recommended(None)


def test_evaluate_response_carries_enforcement_action():
    r = EvaluateResponse(
        trace_id="00000000-0000-0000-0000-000000000001",
        decision="deny",
        score=92.0,
        tags=["x"],
        inference_context={
            "integrity_confidence": 0.2,
            "tamper_risk": 0.7,
            "network_trust": 0.4,
            "replay_risk": 0.1,
            "geo_consistency_risk": 0.3,
            "top_signals": [],
            "confidence_tier": "low",
            "calibration_profile_version": 1,
            "location_confidence": 0.35,
            "confidence_sources": {
                "calibration": "heuristic",
                "counter": "local-fallback",
                "location": "heuristic",
            },
        },
        recommended_action="block",
        enforcement_action=resolve_enforcement_action("deny", "block"),
    )
    assert r.enforcement_action == "block"
