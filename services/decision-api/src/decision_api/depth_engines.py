"""Orchestrate OSS depth engines on evaluate (lifecycle, ring, …, fusion)."""

from __future__ import annotations

from typing import Any

from decision_api.depth_fusion import apply_depth_fusion_features
from decision_api.dispute_representment import apply_representment_features
from decision_api.ftid_intake_gate import apply_ftid_gate_features
from decision_api.graph_hints_merge import merge_partner_hints_into_party_graph
from decision_api.lifecycle_risk import apply_lifecycle_risk_features
from decision_api.listing_risk import apply_listing_risk_features
from decision_api.party_graph_contract import assess_party_graph_quality
from decision_api.promo_economics import apply_promo_economics_features
from decision_api.ring_score import apply_ring_score_features
from decision_api.seller_trajectory import apply_seller_trajectory_features

DEPTH_EVIDENCE_KEYS = (
    "lifecycle_risk",
    "ring_score",
    "seller_trajectory",
    "ftid_intake_gate",
    "promo_economics",
    "dispute_representment",
    "listing_risk",
    "depth_fusion",
    "party_graph_quality",
)


def apply_all_depth_engines(
    features: dict[str, Any],
    payload: dict[str, Any] | None,
    metadata: dict[str, Any] | None,
) -> dict[str, dict[str, Any]]:
    """Run all depth engines; return non-empty evidence keyed for audit."""
    vertical = None
    meta = metadata
    if isinstance(metadata, dict):
        vertical = metadata.get("vertical_profile") or metadata.get("vertical")
        # Best: OCR/partner hints enrich ring inputs before scoring
        merged = merge_partner_hints_into_party_graph(metadata)
        if merged is not None:
            meta = merged

    out: dict[str, dict[str, Any]] = {}

    life = apply_lifecycle_risk_features(
        features,
        payload,
        meta,
        vertical_profile=str(vertical) if vertical else None,
    )
    if life:
        out["lifecycle_risk"] = life

    ring = apply_ring_score_features(features, payload, meta)
    if ring:
        out["ring_score"] = ring

    gq = assess_party_graph_quality(payload=payload, metadata=meta)
    if gq:
        out["party_graph_quality"] = gq
        features["party_graph_quality"] = gq["quality_0_100"]
        features["party_graph_production_ready"] = gq["production_ready"]
        # Honesty: weak graphs cannot silently drive collusion certainty
        if not gq["production_ready"] and features.get("ring_score_high") is True:
            features["ring_graph_quality_weak"] = True

    traj = apply_seller_trajectory_features(features, payload, meta)
    if traj:
        out["seller_trajectory"] = traj

    ftid = apply_ftid_gate_features(features, payload, meta)
    if ftid:
        out["ftid_intake_gate"] = ftid

    promo = apply_promo_economics_features(features, payload, meta)
    if promo:
        out["promo_economics"] = promo

    disp = apply_representment_features(features, payload, meta)
    if disp:
        out["dispute_representment"] = disp

    listing = apply_listing_risk_features(features, payload, meta)
    if listing:
        out["listing_risk"] = listing

    fused = apply_depth_fusion_features(features, out)
    if fused:
        out["depth_fusion"] = fused

    return out


def merge_depth_into_score_and_tags(
    *,
    evidence: dict[str, dict[str, Any]],
    all_new_tags: list[str],
    rule_hits: list[str],
) -> float:
    """Append tags/hits; return depth_delta for base_score.

    Anti-double-count: when fusion is present, child engines contribute at a
    reduced scale (fusion already encodes joint evidence).
    """
    depth_delta = 0.0
    fused = "depth_fusion" in evidence
    child_scale = 0.10 if fused else 0.18
    hit_map = {
        "lifecycle_risk": "lifecycle_risk_engine",
        "ring_score": "ring_score_engine",
        "seller_trajectory": "seller_trajectory_engine",
        "ftid_intake_gate": "ftid_intake_gate_engine",
        "promo_economics": "promo_economics_engine",
        "dispute_representment": "dispute_representment_engine",
        "listing_risk": "listing_risk_engine",
        "depth_fusion": "depth_fusion_engine",
    }
    for key, hit in hit_map.items():
        block = evidence.get(key)
        if not block:
            continue
        all_new_tags.extend(str(t) for t in (block.get("tags") or []) if t)
        rule_hits.append(hit)
        try:
            if key == "dispute_representment":
                score = float(block.get("risk_0_100") or 0)
            else:
                score = float(block.get("score_0_100") or 0)
            if key == "depth_fusion":
                depth_delta += min(22.0, score * 0.22)
            else:
                # Weak host graphs: further damp ring contribution
                scale = child_scale
                if (
                    key == "ring_score"
                    and evidence.get("party_graph_quality", {}).get("production_ready")
                    is False
                ):
                    scale *= 0.5
                depth_delta += min(18.0, score * scale)
        except (TypeError, ValueError):
            pass
    return min(45.0, depth_delta)
