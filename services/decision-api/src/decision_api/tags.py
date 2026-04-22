from __future__ import annotations

from typing import Any

"""Centralized contextual tagging for evaluate responses and audit trails."""


def _safe_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _safe_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _graph_reason_tags(graph_risk: dict[str, Any] | None) -> list[str]:
    if not isinstance(graph_risk, dict):
        return []
    tags: list[str] = []
    for reason in graph_risk.get("risk_factors") or []:
        r = str(reason).strip().lower()
        if not r:
            continue
        if "shared_devices" in r:
            tags.append("ring_shared_device")
        if "large_community" in r:
            tags.append("network_large_community")
        if "connected_flagged" in r:
            tags.append("network_flagged_neighbors")
    return tags


def derive_contextual_tags(
    *,
    features: dict[str, Any],
    signal_tags: list[str],
    graph_risk: dict[str, Any] | None = None,
    external_signal_meta: dict[str, Any] | None = None,
) -> list[str]:
    """Map normalized features/signals into stable, analyst-facing tags."""
    out: list[str] = []
    signals = set(signal_tags)

    ev5 = _safe_int(features.get("event_count_5m"))
    ev1 = _safe_int(features.get("event_count_1h"))
    ev24 = _safe_int(features.get("event_count_24h"))
    if ev5 >= 5:
        out.append("velocity_high_5m")
    if ev1 >= 15:
        out.append("velocity_high_1h")
    if ev24 >= 60:
        out.append("velocity_high_24h")
    if ev24 > 0 and ev1 / max(ev24, 1) > 0.45 and ev1 >= 10:
        out.append("velocity_concentrated_1h")

    if "sdk:geo_ip_mismatch" in signals or bool(features.get("geo_ip_mismatch")):
        out.append("geo_ip_mismatch")
    if "sdk:geo_tz_mismatch" in signals or bool(features.get("geo_tz_mismatch")):
        out.append("geo_tz_mismatch")
    if "sdk:shared_device" in signals:
        out.append("shared_device_detected")
    if "ingress:replay_payload" in signals:
        out.append("replay_payload_detected")

    if isinstance(graph_risk, dict):
        score = _safe_float(graph_risk.get("risk_score"))
        if score >= 70:
            out.append("graph_risk_high")
        elif score >= 40:
            out.append("graph_risk_medium")
        out.extend(_graph_reason_tags(graph_risk))

    if isinstance(external_signal_meta, dict):
        providers = external_signal_meta.get("providers") or []
        for provider in providers:
            p = str(provider).strip().lower()
            if p:
                out.append(f"external_signal:{p}")
        score = _safe_float(external_signal_meta.get("risk_score"))
        if score >= 70:
            out.append("external_signal_high")
        elif score >= 40:
            out.append("external_signal_medium")

    # Preserve stable ordering while deduplicating.
    return list(dict.fromkeys(out))
