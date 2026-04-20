"""Build inference_context (v3) and recommended customer actions (challenge orchestration hints).

SCHEMA_VERSION is the public contract version for OpenAPI + golden parity.
"""

from __future__ import annotations

from typing import Any

from decision_api.integrity_policy import (
    adjust_integrity_confidence,
    haversine_km,
    parse_session_geo,
    trusted_zone_hit,
)

SCHEMA_VERSION = "3"


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def _driver_explain_entry(reason: str) -> dict[str, str]:
    """Analyst-facing category + short label for a driver_reason code."""
    r = reason.strip()
    if r.startswith("rule:"):
        rid = r[5:][:48]
        return {"reason": r, "category": "rules", "label": f"Rule hit: {rid}"}
    if r.startswith("ml_factor:"):
        code = r[10:][:48]
        return {"reason": r, "category": "ml", "label": f"ML factor: {code}"}
    static = {
        "device_tamper_or_emulator_signals": ("device_integrity", "Device tamper / emulator signals"),
        "replay_or_duplicate_payload": ("replay", "Replay or duplicate payload"),
        "hostile_or_anonymous_network_path": ("network", "VPN, proxy, or hostile network path"),
        "geo_or_timezone_inconsistency": ("geo", "Geo or timezone inconsistency"),
        "ml_score_elevated": ("ml", "ML score elevated"),
        "device_seen_across_multiple_entities": ("velocity", "Shared device across entities"),
        "multi_session_velocity": ("velocity", "Multi-session velocity"),
        "velocity_and_geo_suggest_impossible_travel": ("velocity", "Velocity + geo suggest impossible travel"),
    }
    if r in static:
        cat, lbl = static[r]
        return {"reason": r, "category": cat, "label": lbl}
    return {"reason": r, "category": "other", "label": r.replace("_", " ")}


def _confidence_tier_label(tier: str) -> str:
    return {
        "high": "High — integrity signals support confident scoring",
        "medium": "Medium — mixed signals; review edge cases",
        "low": "Low — weak integrity or conflicting signals",
    }.get(tier, "Medium — mixed signals; review edge cases")


def build_inference_context(
    signal_tags: list[str],
    rule_hits: list[str],
    ml_score: float | None,
    final_score: float,
    features: dict[str, Any] | None = None,
    *,
    ml_detail: dict[str, Any] | None = None,
    platform: str = "web",
    tls_pinning_verified: bool | None = None,
    location_meta: dict[str, Any] | None = None,
    counter_meta: dict[str, Any] | None = None,
    calibration_meta: dict[str, Any] | None = None,
    graph_meta: dict[str, Any] | None = None,
    external_signal_meta: dict[str, Any] | None = None,
    policy_experiment_id: str | None = None,
) -> dict[str, Any]:
    """Normalize heterogeneous risk signals into a versioned inference contract (Epic A/E)."""
    features = features or {}
    signal_set = set(signal_tags)

    tamper_markers = ("sdk:repackaged", "sdk:automation", "sdk:emulator", "sdk:shared_device")
    network_markers = ("sdk:vpn", "sdk:proxy", "sdk:datacenter", "sdk:vpn_iface")
    geo_markers = (
        "sdk:spoofed_location",
        "sdk:tz_geo_mismatch",
        "sdk:mock_location",
        "sdk:geo_ip_mismatch",
        "sdk:geo_tz_mismatch",
    )

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

    integrity_confidence = adjust_integrity_confidence(
        integrity_confidence,
        platform,
        list(signal_set),
        pinning_ok=tls_pinning_verified,
    )

    if "sdk:attestation_verified" in signal_set:
        tamper_risk = _clamp01(tamper_risk * 0.82)
        integrity_confidence = _clamp01(integrity_confidence + 0.06)

    # Optional calibration bias from ops (-0.1 .. 0.1) — tenant-specific table via rules injecting feature
    try:
        bias = float(features.get("calibration_bias") or 0.0)
    except (TypeError, ValueError):
        bias = 0.0
    bias = max(-0.1, min(0.1, bias))
    integrity_confidence = _clamp01(integrity_confidence + bias)

    cal_profile = features.get("calibration_profile")
    cal_profile_s = str(cal_profile).strip()[:64] if cal_profile is not None else "default"
    try:
        exp_cal_ver = int(features.get("expected_calibration_version") or 1)
    except (TypeError, ValueError):
        exp_cal_ver = 1
    exp_cal_ver = max(1, min(999999, exp_cal_ver))

    cal_profile_ver = 1
    calibration_source = "heuristic"
    if calibration_meta:
        calibration_source = "service"
        profile_id = calibration_meta.get("profile_id")
        if isinstance(profile_id, str) and profile_id.strip():
            cal_profile_s = profile_id.strip()[:64]
        profile_ver = calibration_meta.get("expected_calibration_version")
        try:
            if profile_ver is not None:
                exp_cal_ver = max(1, min(999999, int(profile_ver)))
        except (TypeError, ValueError):
            pass
        runtime_profile_ver = calibration_meta.get("profile_version")
        try:
            if runtime_profile_ver is not None:
                cal_profile_ver = max(1, min(999999, int(runtime_profile_ver)))
        except (TypeError, ValueError):
            pass
    # --- Epic E: shared-device / velocity heuristics (co-location & impossible travel proxies) ---
    colocation_risk = _clamp01(0.75 if "sdk:shared_device" in signal_set else 0.0)
    distinct_sess = int(features.get("distinct_session_id_24h") or 0)
    if distinct_sess >= 2:
        colocation_risk = max(colocation_risk, _clamp01(0.35 + 0.1 * min(distinct_sess, 5)))

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

    # Session geo: compare last vs previous coordinates (km/h heuristic)
    la, lo, ts = parse_session_geo(features)
    pla, plo, pts = (
        features.get("session_prev_lat"),
        features.get("session_prev_lon"),
        features.get("session_prev_ts"),
    )
    try:
        pla_f = float(pla) if pla is not None else None
        plo_f = float(plo) if plo is not None else None
        pts_f = float(pts) if pts is not None else None
    except (TypeError, ValueError):
        pla_f, plo_f, pts_f = None, None, None
    if la is not None and lo is not None and ts is not None and pla_f is not None and plo_f is not None and pts_f is not None and ts > pts_f:
        dist_km = haversine_km(la, lo, pla_f, plo_f)
        dt_h = max((ts - pts_f) / 3600.0, 1e-6)
        speed = dist_km / dt_h
        if speed > 800:
            travel_boost += 0.45
        elif speed > 120:
            travel_boost += 0.25

    zones = features.get("trusted_zones")
    if isinstance(zones, list) and la is not None and lo is not None and trusted_zone_hit(la, lo, zones):
        travel_boost = max(0.0, travel_boost - 0.35)
        geo_consistency_risk = max(0.0, geo_consistency_risk - 0.2)

    impossible_travel_risk = _clamp01(travel_boost)

    location_confidence = 0.0
    location_source = "heuristic"
    if location_meta:
        location_source = "service"
        try:
            geo_consistency_risk = _clamp01(float(location_meta.get("geo_consistency_risk", geo_consistency_risk)))
        except (TypeError, ValueError):
            pass
        try:
            colocation_risk = _clamp01(float(location_meta.get("copresence_risk", colocation_risk)))
        except (TypeError, ValueError):
            pass
        try:
            impossible_travel_risk = _clamp01(float(location_meta.get("impossible_travel_risk", impossible_travel_risk)))
        except (TypeError, ValueError):
            pass
        try:
            location_confidence = _clamp01(float(location_meta.get("location_confidence", 0.0)))
        except (TypeError, ValueError):
            pass

    counter_source = "heuristic"
    if counter_meta:
        counter_source = "service"
        counters = counter_meta.get("counters")
        if isinstance(counters, dict):
            ev5 = counters.get("event_count_5m")
            ev1 = counters.get("event_count_1h")
            ev24 = counters.get("event_count_24h")
            try:
                if ev5 is not None:
                    features["event_count_5m"] = int(ev5)
            except (TypeError, ValueError):
                pass
            try:
                if ev1 is not None:
                    features["event_count_1h"] = int(ev1)
            except (TypeError, ValueError):
                pass
            try:
                if ev24 is not None:
                    features["event_count_24h"] = int(ev24)
            except (TypeError, ValueError):
                pass
    elif any(k in features for k in ("event_count_5m", "event_count_1h", "event_count_24h")):
        counter_source = "local-fallback"

    graph_risk_score = 0.0
    graph_risk_reasons: list[str] = []
    if graph_meta:
        try:
            graph_risk_score = _clamp01(float(graph_meta.get("risk_score", 0.0)) / 100.0)
        except (TypeError, ValueError):
            graph_risk_score = 0.0
        raw_graph_reasons = graph_meta.get("risk_factors")
        if isinstance(raw_graph_reasons, list):
            graph_risk_reasons = [str(x).strip() for x in raw_graph_reasons if str(x).strip()][:8]

    external_signal_score = 0.0
    external_signal_providers: list[str] = []
    if external_signal_meta:
        try:
            score_raw = external_signal_meta.get("risk_score")
            if score_raw is None:
                score_raw = float(external_signal_meta.get("score_delta", 0.0)) * 5.0
            external_signal_score = _clamp01(float(score_raw) / 100.0)
        except (TypeError, ValueError):
            external_signal_score = 0.0
        providers = external_signal_meta.get("providers")
        if isinstance(providers, list):
            external_signal_providers = [str(x).strip() for x in providers if str(x).strip()]

    try:
        ev1h = int(features.get("event_count_1h") or ev1h)
    except (TypeError, ValueError):
        ev1h = int(ev1h)
    try:
        ev24 = int(features.get("event_count_24h") or ev24)
    except (TypeError, ValueError):
        ev24 = int(ev24)

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
    if distinct_sess >= 2:
        driver_reasons.append("multi_session_velocity")
    if impossible_travel_risk >= 0.45:
        driver_reasons.append("velocity_and_geo_suggest_impossible_travel")
    for rh in rule_hits[:5]:
        if rh and rh not in ("whitelist_bypass", "blacklist_block", "test_bypass"):
            driver_reasons.append(f"rule:{rh}")

    ml_top_factors: list[dict[str, Any]] = []
    ml_summary: str | None = None
    ml_model: str | None = None
    if ml_detail:
        raw_factors = ml_detail.get("top_factors")
        if isinstance(raw_factors, list):
            ml_top_factors = [x for x in raw_factors if isinstance(x, dict)][:5]
        ml_summary = ml_detail.get("summary") if isinstance(ml_detail.get("summary"), str) else None
        m = ml_detail.get("model")
        ml_model = str(m).strip()[:256] if m else None
        for fac in ml_top_factors[:2]:
            code = fac.get("code")
            if code:
                tag = f"ml_factor:{code}"
                if tag not in driver_reasons:
                    driver_reasons.append(tag)
    driver_reasons = driver_reasons[:8]

    driver_explain = [_driver_explain_entry(d) for d in driver_reasons]

    ordered_top = sorted(signal_set)[:5]

    return {
        "schema_version": SCHEMA_VERSION,
        "calibration_profile": cal_profile_s,
        "expected_calibration_version": exp_cal_ver,
        "confidence_tier_label": _confidence_tier_label(confidence_tier),
        "driver_explain": driver_explain,
        "integrity_confidence": round(integrity_confidence, 4),
        "tamper_risk": round(tamper_risk, 4),
        "network_trust": round(network_trust, 4),
        "replay_risk": round(replay_risk, 4),
        "geo_consistency_risk": round(geo_consistency_risk, 4),
        "top_signals": ordered_top,
        "confidence_tier": confidence_tier,
        "driver_reasons": driver_reasons,
        "colocation_risk": round(colocation_risk, 4),
        "copresence_risk": round(colocation_risk, 4),
        "impossible_travel_risk": round(impossible_travel_risk, 4),
        "velocity_events_5m": int(features.get("event_count_5m") or 0),
        "velocity_events_1h": ev1h,
        "velocity_events_24h": ev24,
        "calibration_profile_version": cal_profile_ver,
        "location_confidence": round(location_confidence, 4),
        "confidence_sources": {
            "calibration": calibration_source,
            "counter": counter_source,
            "location": location_source,
        },
        "graph_risk_score": round(graph_risk_score, 4),
        "graph_risk_reasons": graph_risk_reasons,
        "external_signal_score": round(external_signal_score, 4),
        "external_signal_providers": external_signal_providers,
        "policy_experiment_id": policy_experiment_id.strip()[:128] if isinstance(policy_experiment_id, str) and policy_experiment_id.strip() else None,
        "ml_top_factors": ml_top_factors,
        "ml_summary": ml_summary,
        "ml_model": ml_model,
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
