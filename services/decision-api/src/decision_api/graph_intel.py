from typing import Any

from decision_api.graph_entity_risk_types import NEIGHBOR_DEVICE_COUNT_HIGH_THRESHOLD


def graph_score_delta(risk_score: float | int | None) -> float:
    if risk_score is None:
        return 0.0
    try:
        score = max(0.0, min(100.0, float(risk_score)))
    except (TypeError, ValueError):
        return 0.0
    # Convert graph risk 0-100 into additive impact up to +20.
    return round((score / 100.0) * 20.0, 2)


def graph_tags_from_risk(payload: dict[str, Any] | None) -> list[str]:
    if not isinstance(payload, dict):
        return []
    tags: list[str] = []
    try:
        risk = float(payload.get("risk_score", 0.0) or 0.0)
    except (TypeError, ValueError):
        risk = 0.0
    if risk >= 70:
        tags.append("graph:high_risk_entity")
    elif risk >= 40:
        tags.append("graph:medium_risk_entity")

    try:
        neighbor_device_count = int(payload.get("neighbor_device_count") or 0)
    except (TypeError, ValueError):
        neighbor_device_count = 0
    if neighbor_device_count >= NEIGHBOR_DEVICE_COUNT_HIGH_THRESHOLD:
        tags.append("graph:neighbor_device_count_high")

    factors = payload.get("risk_factors") or []
    if isinstance(factors, list):
        for factor in factors[:5]:
            sf = str(factor).strip()
            if sf:
                tags.append(f"graph:{sf}")
    return tags
