"""Build inference_context (v2) and recommended customer actions (challenge orchestration hints)."""

from __future__ import annotations

from typing import Any


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def build_inference_context(
    signal_tags: list[str],
    rule_hits: list[str],
    ml_score: float | None,
    final_score: float,
    features: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Normalize heterogeneous risk signals into a versioned inference contract (Epic A/E)."""
    features = features or {}
    signal_set = set(signal_tags)

    tamper_markers = ("sdk:repackaged", "sdk:automation", "sdk:emulator", "sdk:shared_device")
    network_markers = ("sdk:vpn", "sdk:proxy", "sdk:datacenter", "sdk:vpn_iface")
    geo_markers = ("sdk:spoofed_location", "sdk:tz_geo_mismatch", "sdk:mock_location")

    tamper_hits = sum(1 for m in tamper_markers if m in signal_set)
    network_hits = sum(1 for m in network_markers if m in signal_set)
    geo_hits = sum(1 for m in geo_markers if m in signal_set)
    replay_hits = sum(1 for h in rule_hits if "replay" in h.lower())
    if "ingress:replay_payload" in signal_set:
        replay_hits += 1

    tamper_risk = _clamp01(tamper_hits / max(1, len(tamper_markers)))
    network_risk = _clamp01(network_hits / max(1, len(network_markers)))
    geo_consistency_risk = _clamp01(geo_hits / max(1, len(geo_markers)))
    replay_risk = _clamp01(replay_hits / 2.0)

    network_trust = _clamp01(1.0 - network_risk)
    score_factor = _clamp01(final_score / 100.0)
    model_factor = _clamp01((ml_score or 0.0) / 100.0)
    integrity_confidence = _clamp01(
        1.0 - (0.35 * tamper_risk + 0.2 * network_risk + 0.15 * replay_risk + 0.15 * geo_consistency_risk) - (0.15 * max(score_factor, model_factor))
    )

    # --- Epic E: shared-device / velocity heuristics (co-location & impossible travel proxies) ---
    colocation_risk = _clamp01(0.75 if "sdk:shared_device" in signal_set else 0.0)

    ev1h = int(features.get("event_count_1h") or 0)
    ev24 = int(features.get("event_count_24h") or 0)
    distinct_dev = int(features.get("distinct_device_id_24h") or 0)
    travel_boost = 0.0
    if distinct_dev >= 3 and ev1h >= 5:
        travel_boost += 0.35
    if geo_consistency_risk >= 0.34 and ev1h >= 8:
        travel_boost += 0.3
    if ev24 > 0 and ev1h / max(ev24, 1) > 0.5 and ev1h > 15:
        travel_boost += 0.2
    impossible_travel_risk = _clamp01(travel_boost)

    # Epic A: tier + analyst-facing drivers
    if integrity_confidence >= 0.72:
        confidence_tier = "high"
    elif integrity_confidence >= 0.42:
        confidence_tier = "medium"
    else:
        confidence_tier = "low"

    driver_reasons: list[str] = []
    if tamper_risk >= 0.5:
        driver_reasons.append("device_tamper_or_emulator_signals")
    if replay_risk >= 0.5:
        driver_reasons.append("replay_or_duplicate_payload")
    if network_trust <= 0.45:
        driver_reasons.append("hostile_or_anonymous_network_path")
    if geo_consistency_risk >= 0.34:
        driver_reasons.append("geo_or_timezone_inconsistency")
    if ml_score is not None and ml_score >= 70.0:
        driver_reasons.append("ml_score_elevated")
    if colocation_risk >= 0.5:
        driver_reasons.append("device_seen_across_multiple_entities")
    if impossible_travel_risk >= 0.45:
        driver_reasons.append("velocity_and_geo_suggest_impossible_travel")
    for rh in rule_hits[:5]:
        if rh and rh not in ("whitelist_bypass", "blacklist_block", "test_bypass"):
            driver_reasons.append(f"rule:{rh}")
    driver_reasons = driver_reasons[:8]

    ordered_top = sorted(signal_set)[:5]

    return {
        "schema_version": "2",
        "integrity_confidence": round(integrity_confidence, 4),
        "tamper_risk": round(tamper_risk, 4),
        "network_trust": round(network_trust, 4),
        "replay_risk": round(replay_risk, 4),
        "geo_consistency_risk": round(geo_consistency_risk, 4),
        "top_signals": ordered_top,
        "confidence_tier": confidence_tier,
        "driver_reasons": driver_reasons,
        "colocation_risk": round(colocation_risk, 4),
        "impossible_travel_risk": round(impossible_travel_risk, 4),
        "velocity_events_5m": int(features.get("event_count_5m") or 0),
        "velocity_events_1h": ev1h,
        "velocity_events_24h": ev24,
    }


def derive_recommended_action(decision: str, signal_tags: list[str], inference: dict[str, Any]) -> str | None:
    """Epic D: low-friction-first hint for clients (not a substitute for policy engines)."""
    tags = set(signal_tags)
    tier = inference.get("confidence_tier", "medium")

    if decision == "deny":
        return "block"

    if decision == "review":
        return "step_up_mfa" if tier == "low" else "manual_review"

    if "ingress:replay_payload" in tags:
        return "step_up_attestation"
    if inference.get("tamper_risk", 0) >= 0.5 or inference.get("replay_risk", 0) >= 0.5:
        return "step_up_attestation"
    if tier == "low":
        return "step_up_mfa"
    if inference.get("impossible_travel_risk", 0) >= 0.55:
        return "step_up_mfa"
    return None
