"""Tests for inference_context v2 and recommended_action hints."""
from decision_api.inference_build import build_inference_context, derive_recommended_action


def test_build_inference_context_schema_and_velocity():
    ctx = build_inference_context(
        signal_tags=["sdk:vpn"],
        rule_hits=[],
        ml_score=None,
        final_score=40.0,
        features={
            "event_count_5m": 3,
            "event_count_1h": 10,
            "event_count_24h": 100,
        },
    )
    assert ctx["schema_version"] == "2"
    assert ctx["velocity_events_5m"] == 3
    assert ctx["velocity_events_1h"] == 10
    assert ctx["velocity_events_24h"] == 100
    assert ctx["confidence_tier"] in ("low", "medium", "high")
    assert isinstance(ctx["driver_reasons"], list)
    assert isinstance(ctx["top_signals"], list)


def test_build_inference_context_colocation_and_travel():
    ctx = build_inference_context(
        signal_tags=["sdk:shared_device", "sdk:spoofed_location"],
        rule_hits=[],
        ml_score=None,
        final_score=50.0,
        features={
            "event_count_1h": 20,
            "event_count_24h": 30,
            "distinct_device_id_24h": 4,
        },
    )
    assert ctx["colocation_risk"] >= 0.5
    assert ctx["impossible_travel_risk"] > 0


def test_derive_recommended_action_deny_and_review():
    inf = {"confidence_tier": "high", "tamper_risk": 0.0, "replay_risk": 0.0}
    assert derive_recommended_action("deny", [], inf) == "block"
    assert derive_recommended_action("review", [], inf) == "manual_review"
    assert derive_recommended_action("review", [], {"confidence_tier": "low"}) == "step_up_mfa"


def test_derive_recommended_action_allow_attestation():
    inf_high = {"confidence_tier": "high", "tamper_risk": 0.0, "replay_risk": 0.0}
    assert derive_recommended_action("allow", ["ingress:replay_payload"], inf_high) == "step_up_attestation"
    assert derive_recommended_action("allow", [], {"tamper_risk": 0.6}) == "step_up_attestation"
    assert derive_recommended_action("allow", [], {"confidence_tier": "low"}) == "step_up_mfa"
    assert derive_recommended_action("allow", [], {"impossible_travel_risk": 0.6}) == "step_up_mfa"
    assert derive_recommended_action("allow", [], inf_high) is None
