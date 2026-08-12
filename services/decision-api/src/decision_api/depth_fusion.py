"""Cross-engine depth fusion — gated co-occurrence with anti-double-count."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

SCHEMA_ID = "tarka.depth_fusion/v1"
METHOD = "gated_cooccurrence_v2"

_SOFT_FLOOR = 40.0
# Diminishing returns on stacked pair recipes (best: avoid sum-of-pairs inflation)
_DIMINISH = 0.65

# (engine_a, engine_b, factor_code, weight, tags, required_any_features)
# required_any empty → pure co-occurrence; else ≥1 feature must be true
_PAIR_RECIPES: tuple[
    tuple[str, str, str, float, tuple[str, ...], tuple[str, ...]], ...
] = (
    (
        "lifecycle_risk",
        "ring_score",
        "lifecycle_ring",
        28.0,
        ("risk:collusion_refund_farm", "action:hard_challenge"),
        ("lifecycle_risk_high", "cross_role_same_device", "ring_score_high"),
    ),
    (
        "lifecycle_risk",
        "ftid_intake_gate",
        "lifecycle_ftid",
        30.0,
        ("risk:ftid", "action:refund_hold"),
        ("ftid_refund_hold", "lifecycle_factor:refund_before_delivery"),
    ),
    (
        "ring_score",
        "promo_economics",
        "ring_promo",
        24.0,
        ("risk:promo_farm", "action:hard_challenge"),
        (
            "promo_econ_high",
            "ring_factor:promo_device_role_chain",
            "cross_role_same_device",
        ),
    ),
    (
        "seller_trajectory",
        "ftid_intake_gate",
        "trajectory_ftid",
        26.0,
        ("action:payout_hold", "action:refund_hold"),
        ("seller_trajectory_high", "ftid_refund_hold"),
    ),
    (
        "lifecycle_risk",
        "dispute_representment",
        "lifecycle_representment",
        22.0,
        ("risk:friendly_fraud", "action:dispute_evidence_gap"),
        ("representment_weak", "lifecycle_risk_high"),
    ),
    (
        "ring_score",
        "seller_trajectory",
        "ring_trajectory",
        20.0,
        ("risk:seller_collusion", "action:hard_challenge"),
        ("ring_score_high", "seller_trajectory_high"),
    ),
    (
        "ftid_intake_gate",
        "dispute_representment",
        "ftid_representment",
        28.0,
        ("risk:friendly_fraud", "action:refund_hold", "action:dispute_evidence_gap"),
        ("ftid_refund_hold", "representment_weak"),
    ),
    (
        "lifecycle_risk",
        "promo_economics",
        "lifecycle_promo",
        22.0,
        ("risk:promo_refund_loop", "action:hard_challenge"),
        ("promo_econ_high", "promo_factor:refund_after_promo", "lifecycle_risk_high"),
    ),
    (
        "promo_economics",
        "ftid_intake_gate",
        "promo_ftid",
        24.0,
        ("risk:promo_farm", "risk:ftid", "action:refund_hold"),
        ("promo_econ_high", "ftid_refund_hold"),
    ),
    (
        "ring_score",
        "ftid_intake_gate",
        "ring_ftid",
        26.0,
        ("risk:collusion_refund_farm", "action:refund_hold", "action:hard_challenge"),
        ("cross_role_same_device", "ftid_refund_hold", "ring_score_high"),
    ),
    (
        "seller_trajectory",
        "lifecycle_risk",
        "trajectory_lifecycle",
        20.0,
        ("risk:seller_trajectory", "action:payout_hold"),
        ("seller_trajectory_high", "lifecycle_risk_high"),
    ),
    (
        "promo_economics",
        "dispute_representment",
        "promo_representment",
        18.0,
        ("risk:friendly_fraud", "action:dispute_evidence_gap"),
        ("promo_econ_high", "representment_weak"),
    ),
    (
        "seller_trajectory",
        "dispute_representment",
        "trajectory_representment",
        18.0,
        ("action:payout_hold", "action:dispute_evidence_gap"),
        ("seller_trajectory_high", "representment_weak"),
    ),
    (
        "ring_score",
        "dispute_representment",
        "ring_representment",
        16.0,
        ("risk:collusion_shared_device", "action:dispute_evidence_gap"),
        ("ring_score_high", "representment_weak"),
    ),
    (
        "promo_economics",
        "seller_trajectory",
        "promo_trajectory",
        20.0,
        ("risk:promo_farm", "action:payout_hold"),
        ("promo_econ_high", "seller_trajectory_high"),
    ),
    (
        "listing_risk",
        "seller_trajectory",
        "listing_trajectory",
        22.0,
        ("risk:counterfeit", "action:payout_hold", "action:listing_takedown"),
        ("listing_risk_high", "seller_trajectory_high"),
    ),
    (
        "listing_risk",
        "ring_score",
        "listing_ring",
        20.0,
        ("risk:live_commerce", "action:hard_challenge"),
        ("listing_risk_high", "ring_score_high"),
    ),
)

_HARD_FLAGS: dict[str, tuple[str, ...]] = {
    "lifecycle_risk": ("lifecycle_risk_high",),
    "ring_score": ("ring_score_high", "cross_role_same_device"),
    "seller_trajectory": ("seller_trajectory_high",),
    "ftid_intake_gate": ("ftid_refund_hold", "ftid_high"),
    "promo_economics": ("promo_econ_high",),
    "dispute_representment": ("representment_weak",),
    "listing_risk": ("listing_risk_high",),
}


@dataclass
class FusionFactor:
    code: str
    weight: float
    detail: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "weight": round(self.weight, 2),
            "detail": self.detail,
        }


@dataclass
class DepthFusionResult:
    score_0_100: float
    active_engines: list[str] = field(default_factory=list)
    factors: list[FusionFactor] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)

    def evidence(self) -> dict[str, Any]:
        return {
            "schema_id": SCHEMA_ID,
            "method": METHOD,
            "score_0_100": round(self.score_0_100, 2),
            "active_engines": list(self.active_engines),
            "active_count": len(self.active_engines),
            "factors": [f.as_dict() for f in self.factors],
            "tags": list(self.tags),
            "double_count_control": "diminishing_returns_v1",
            "live_claim_allowed": False,
            "gnn_claim_allowed": False,
        }


def _child_score(block: dict[str, Any], engine_id: str) -> float:
    try:
        if engine_id == "dispute_representment":
            return float(block.get("risk_0_100") or 0)
        return float(block.get("score_0_100") or 0)
    except (TypeError, ValueError):
        return 0.0


def _is_active(
    engine_id: str,
    block: dict[str, Any] | None,
    features: dict[str, Any],
) -> bool:
    if not isinstance(block, dict) or not block:
        return False
    if _child_score(block, engine_id) >= _SOFT_FLOOR:
        return True
    for flag in _HARD_FLAGS.get(engine_id, ()):
        if features.get(flag) is True:
            return True
    if engine_id == "ring_score" and block.get("cross_role_same_device") is True:
        return True
    if engine_id == "ftid_intake_gate" and block.get("refund_hold") is True:
        return True
    return False


def _gate_ok(required_any: tuple[str, ...], features: dict[str, Any]) -> bool:
    if not required_any:
        return True
    return any(features.get(f) is True for f in required_any)


def compute_depth_fusion(
    *,
    evidence: dict[str, dict[str, Any]],
    features: dict[str, Any],
) -> DepthFusionResult | None:
    """Fuse active child engines via gated pair recipes; None if <2 active."""
    active = [
        eid
        for eid in (
            "lifecycle_risk",
            "ring_score",
            "seller_trajectory",
            "ftid_intake_gate",
            "promo_economics",
            "dispute_representment",
            "listing_risk",
        )
        if _is_active(eid, evidence.get(eid), features)
    ]
    if len(active) < 2:
        return None

    active_set = set(active)
    raw_hits: list[tuple[str, float, tuple[str, ...], str]] = []
    for a, b, code, weight, recipe_tags, required in _PAIR_RECIPES:
        if a in active_set and b in active_set and _gate_ok(required, features):
            raw_hits.append(
                (code, weight, recipe_tags, f"Gated co-occurrence of {a} × {b}")
            )

    factors: list[FusionFactor] = []
    tags: list[str] = ["risk:depth_fusion"]
    pair_sum = 0.0

    if not raw_hits:
        factors.append(
            FusionFactor(
                code="multi_engine",
                weight=10.0,
                detail=f"{len(active)} engines active without gated pair recipe",
            )
        )
        pair_sum = 10.0
    else:
        # Heaviest recipes first; diminish subsequent weights
        raw_hits.sort(key=lambda x: x[1], reverse=True)
        for i, (code, weight, recipe_tags, detail) in enumerate(raw_hits):
            adj = weight * (_DIMINISH**i)
            factors.append(
                FusionFactor(
                    code=code,
                    weight=adj,
                    detail=detail + (f" (diminish^{i})" if i else ""),
                )
            )
            pair_sum += adj
            tags.extend(recipe_tags)

    max_child = max(_child_score(evidence[e], e) for e in active)
    lift = min(12.0, 0.06 * max_child) if len(active) >= 3 else 0.0
    # Tighter cap than v1 — multi-recipe stacks must not dominate (lift inside cap)
    score = max(0.0, min(62.0, pair_sum + lift))
    if score >= 45.0:
        tags.append("action:hard_challenge")
    return DepthFusionResult(
        score_0_100=score,
        active_engines=active,
        factors=factors,
        tags=list(dict.fromkeys(tags)),
    )


def apply_depth_fusion_features(
    features: dict[str, Any],
    evidence: dict[str, dict[str, Any]],
) -> dict[str, Any] | None:
    """Mutate features from fusion; return evidence or None."""
    result = compute_depth_fusion(evidence=evidence, features=features)
    if result is None:
        return None
    features["depth_fusion_score"] = round(result.score_0_100, 2)
    features["depth_fusion_active_count"] = len(result.active_engines)
    features["depth_fusion_high"] = result.score_0_100 >= 45.0 or any(
        f.code
        in (
            "lifecycle_ring",
            "lifecycle_ftid",
            "ftid_representment",
            "ring_ftid",
            "promo_ftid",
            "listing_trajectory",
        )
        for f in result.factors
    )
    for f in result.factors:
        features[f"fusion_factor:{f.code}"] = True
    return result.evidence()
