"""Entity resolution confidence heuristics for graph link API fields."""

from __future__ import annotations

from typing import Any, Literal

ConfidenceLabel = Literal["high", "medium", "low"]

_REL_BASE_SCORE: dict[str, float] = {
    "USED_DEVICE": 0.88,
    "ORDERED_FROM_IP": 0.62,
    "SHARED_WITH": 0.72,
    "REFERRED": 0.58,
    "KYC_VERIFIED_BY": 0.80,
    "OWNS": 0.75,
    "RELATED": 0.55,
    "USED": 0.70,
}


def _clamp_score(value: float) -> float:
    return max(0.0, min(1.0, round(value, 3)))


def _label_for_score(score: float) -> ConfidenceLabel:
    if score >= 0.8:
        return "high"
    if score >= 0.6:
        return "medium"
    return "low"


def resolution_confidence_for_link(
    *,
    rel: str,
    network: dict[str, Any],
    shared_target_count: int = 1,
) -> dict[str, Any]:
    """
    Deterministic heuristic confidence for a single graph viz link (API-only; no ML).

    Factors: relationship strength prior, neighborhood density, blocked-device proximity.
    """
    rel_token = (rel or "RELATED").strip().upper() or "RELATED"
    score = _REL_BASE_SCORE.get(rel_token, 0.55)
    factors: list[str] = [f"rel_prior:{rel_token}"]

    neighbor_count = int(network.get("neighbor_node_count") or 0)
    if neighbor_count > 16:
        score -= 0.08
        factors.append("dense_neighborhood")
    elif neighbor_count > 8:
        score -= 0.04
        factors.append("moderate_neighborhood")

    blocked_touches = int(network.get("blocked_device_touch_count") or 0)
    if blocked_touches > 0 and rel_token == "USED_DEVICE":
        score -= 0.18
        factors.append("blocked_device_proximity")

    if shared_target_count > 1:
        penalty = min(0.12, 0.04 * (shared_target_count - 1))
        score -= penalty
        factors.append(f"shared_target_x{shared_target_count}")

    if bool(network.get("found")):
        score += 0.02
        factors.append("anchor_found_in_graph")

    final_score = _clamp_score(score)
    return {
        "resolution_confidence": final_score,
        "confidence_label": _label_for_score(final_score),
        "confidence_factors": factors,
    }


def annotate_graph_links(
    links: list[dict[str, Any]],
    network: dict[str, Any],
) -> list[dict[str, Any]]:
    """Attach resolution confidence fields to each link dict (mutates copies)."""
    target_counts: dict[str, int] = {}
    for link in links:
        target = str(link.get("target") or "")
        if target:
            target_counts[target] = target_counts.get(target, 0) + 1

    annotated: list[dict[str, Any]] = []
    for link in links:
        out = dict(link)
        rel = str(out.get("rel") or "RELATED")
        target = str(out.get("target") or "")
        conf = resolution_confidence_for_link(
            rel=rel,
            network=network,
            shared_target_count=target_counts.get(target, 1),
        )
        out.update(conf)
        annotated.append(out)
    return annotated
