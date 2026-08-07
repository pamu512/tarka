"""Tests for inference_context v3 and recommended_action hints."""

from decision_api.inference_build import (
    build_inference_context,
    derive_recommended_action,
)


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
    assert ctx["schema_version"] == "3"
    assert ctx["calibration_profile"] == "default"
    assert ctx["expected_calibration_version"] == 1
    assert ctx["velocity_events_5m"] == 3
    assert ctx["velocity_events_1h"] == 10
    assert ctx["velocity_events_24h"] == 100
    assert ctx["confidence_tier"] in ("low", "medium", "high")
    assert (
        isinstance(ctx.get("confidence_tier_label"), str)
        and ctx["confidence_tier_label"]
    )
    assert isinstance(ctx.get("driver_explain"), list)
    assert isinstance(ctx["driver_reasons"], list)
    assert isinstance(ctx["top_signals"], list)
    assert isinstance(ctx["graph_risk_reasons"], list)
    assert isinstance(ctx["external_signal_providers"], list)
    assert ctx["policy_experiment_id"] is None
    assert ctx["ml_top_factors"] == []
    assert ctx["ml_summary"] is None
    assert ctx["ml_model"] is None


def test_build_inference_context_graph_and_external_meta():
    ctx = build_inference_context(
        signal_tags=[],
        rule_hits=[],
        ml_score=None,
        final_score=45.0,
        features={},
        graph_meta={"risk_score": 80, "risk_factors": ["connected_flagged_3"]},
        external_signal_meta={"risk_score": 68, "providers": ["scameter"]},
        policy_experiment_id="policy-exp-001",
    )
    assert ctx["graph_risk_score"] == 0.8
    assert ctx["graph_risk_reasons"] == ["connected_flagged_3"]
    assert ctx["external_signal_score"] == 0.68
    assert ctx["external_signal_providers"] == ["scameter"]
    assert ctx["policy_experiment_id"] == "policy-exp-001"


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


def test_colocation_risk_is_max_of_split_components():
    ctx_device = build_inference_context(
        signal_tags=["sdk:shared_device"],
        rule_hits=[],
        ml_score=None,
        final_score=50.0,
        features={},
    )
    assert ctx_device["shared_device_risk"] > 0
    assert ctx_device["graph_peer_risk"] == 0.0
    assert ctx_device["geo_copresence_risk"] == 0.0
    assert ctx_device["colocation_risk"] == ctx_device["shared_device_risk"]

    ctx_geo = build_inference_context(
        signal_tags=[],
        rule_hits=[],
        ml_score=None,
        final_score=50.0,
        features={},
        location_meta={"copresence_risk": 0.7},
    )
    assert ctx_geo["geo_copresence_risk"] == 0.7
    assert ctx_geo["shared_device_risk"] == 0.0
    assert ctx_geo["graph_peer_risk"] == 0.0
    assert ctx_geo["colocation_risk"] == 0.7

    ctx_graph = build_inference_context(
        signal_tags=[],
        rule_hits=[],
        ml_score=None,
        final_score=50.0,
        features={"graph_seen_at_peer_count_24h": 4},
        graph_meta={"seen_at_peer_count_24h": 4},
    )
    assert ctx_graph["graph_peer_risk"] > 0
    assert ctx_graph["colocation_risk"] == max(
        ctx_graph["shared_device_risk"],
        ctx_graph["graph_peer_risk"],
        ctx_graph["geo_copresence_risk"],
    )

    ctx_all = build_inference_context(
        signal_tags=["sdk:shared_device"],
        rule_hits=[],
        ml_score=None,
        final_score=50.0,
        features={"graph_seen_at_peer_count_24h": 6},
        graph_meta={"seen_at_peer_count_24h": 6},
        location_meta={"copresence_risk": 0.55},
    )
    assert ctx_all["colocation_risk"] == max(
        ctx_all["shared_device_risk"],
        ctx_all["graph_peer_risk"],
        ctx_all["geo_copresence_risk"],
    )
    assert ctx_all["copresence_risk"] == ctx_all["colocation_risk"]


def test_derive_recommended_action_deny_and_review():
    inf = {"confidence_tier": "high", "tamper_risk": 0.0, "replay_risk": 0.0}
    assert derive_recommended_action("deny", [], inf) == "block"
    assert derive_recommended_action("review", [], inf) == "manual_review"
    assert (
        derive_recommended_action("review", [], {"confidence_tier": "low"})
        == "step_up_mfa"
    )


def test_derive_recommended_action_integrity_gates_step_up():
    # Below web floor (0.55) → manual_review instead of auto step-up.
    low = {
        "confidence_tier": "low",
        "platform": "web",
        "integrity_confidence": 0.4,
        "tamper_risk": 0.0,
        "replay_risk": 0.0,
    }
    assert derive_recommended_action("allow", [], low) == "manual_review"
    # Deny still blocks regardless of integrity.
    assert derive_recommended_action("deny", [], low) == "block"
    ok = {**low, "integrity_confidence": 0.8}
    assert derive_recommended_action("allow", [], ok) == "step_up_mfa"


def test_build_inference_context_ml_detail():
    ctx = build_inference_context(
        signal_tags=[],
        rule_hits=[],
        ml_score=72.0,
        final_score=72.0,
        features={"amount": 100},
        ml_detail={
            "top_factors": [
                {"code": "HIGH_AMOUNT", "description": "Big txn", "impact": "high"}
            ],
            "summary": "ML risk score 72.0/100 (test). Top signals: HIGH_AMOUNT: Big txn",
            "model": "heuristic-v1",
        },
    )
    assert len(ctx["ml_top_factors"]) == 1
    assert ctx["ml_top_factors"][0]["code"] == "HIGH_AMOUNT"
    assert "ml_factor:HIGH_AMOUNT" in ctx["driver_reasons"]
    assert ctx["ml_summary"] is not None
    assert ctx["ml_model"] == "heuristic-v1"


def test_derive_recommended_action_allow_attestation():
    inf_high = {
        "confidence_tier": "high",
        "tamper_risk": 0.0,
        "replay_risk": 0.0,
        "integrity_confidence": 0.9,
        "platform": "web",
    }
    assert (
        derive_recommended_action("allow", ["ingress:replay_payload"], inf_high)
        == "step_up_attestation"
    )
    assert (
        derive_recommended_action(
            "allow",
            [],
            {"tamper_risk": 0.6, "integrity_confidence": 0.9, "platform": "web"},
        )
        == "step_up_attestation"
    )
    assert (
        derive_recommended_action(
            "allow",
            [],
            {"confidence_tier": "low", "integrity_confidence": 0.9, "platform": "web"},
        )
        == "step_up_mfa"
    )
    assert (
        derive_recommended_action(
            "allow",
            [],
            {
                "impossible_travel_risk": 0.6,
                "integrity_confidence": 0.9,
                "platform": "web",
            },
        )
        == "step_up_mfa"
    )
    assert derive_recommended_action("allow", [], inf_high) is None
