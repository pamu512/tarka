"""Promo economics fusion — margin erosion + stack interaction (no LIVE).

Composes discount lines, redeem velocity, and optional loyalty friction heads
into an econ_abuse_score with factor breakdown.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

SCHEMA_ID = "tarka.promo_economics/v1"
METHOD = "margin_stack_heuristic_v1"


@dataclass
class PromoFactor:
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
class PromoEconomicsResult:
    score_0_100: float
    margin_ratio: float | None
    stack_depth: int
    factors: list[PromoFactor] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)

    def evidence(self) -> dict[str, Any]:
        return {
            "schema_id": SCHEMA_ID,
            "score_0_100": round(self.score_0_100, 2),
            "margin_ratio": (
                round(self.margin_ratio, 4) if self.margin_ratio is not None else None
            ),
            "stack_depth": self.stack_depth,
            "factors": [f.as_dict() for f in self.factors],
            "tags": list(self.tags),
            "method": METHOD,
            "live_amplification": (
                "Loyalty-abuse bridge heads merge into friction_heads; catalog "
                "costs refine margin_ratio."
            ),
        }


def _f(v: Any) -> float | None:
    try:
        if v is None or isinstance(v, bool):
            return None
        return float(v)
    except (TypeError, ValueError):
        return None


def _i(v: Any) -> int | None:
    try:
        if v is None or isinstance(v, bool):
            return None
        return int(v)
    except (TypeError, ValueError):
        return None


def _extract(
    payload: dict[str, Any] | None, metadata: dict[str, Any] | None
) -> dict[str, Any] | None:
    for src in (metadata, payload):
        if not isinstance(src, dict):
            continue
        block = src.get("promo_economics") or src.get("promo")
        if isinstance(block, dict):
            return block
    return None


def _add(factors: list[PromoFactor], code: str, weight: float, detail: str) -> None:
    if weight <= 0:
        return
    factors.append(PromoFactor(code=code, weight=min(36.0, weight), detail=detail))


def compute_promo_economics(
    *,
    payload: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
) -> PromoEconomicsResult | None:
    block = _extract(payload, metadata)
    if block is None:
        return None

    list_price = _f(block.get("list_price") or block.get("list_amount"))
    paid = _f(block.get("paid_amount") or block.get("paid"))
    discounts = (
        block.get("discounts") if isinstance(block.get("discounts"), list) else []
    )
    aov = _f(block.get("aov_30d"))
    ltv = _f(block.get("ltv_proxy") or block.get("ltv"))
    age = _f(block.get("account_age_days"))
    redeem_24h = _i(block.get("redeem_count_24h"))
    friction = (
        block.get("friction_heads")
        if isinstance(block.get("friction_heads"), dict)
        else {}
    )

    # Need at least price path or discount stack or redeem velocity
    if list_price is None and paid is None and not discounts and redeem_24h is None:
        return None

    factors: list[PromoFactor] = []
    stack_depth = 0
    discount_total = 0.0
    types: set[str] = set()
    for d in discounts:
        if not isinstance(d, dict):
            continue
        stack_depth += 1
        amt = _f(d.get("amount"))
        if amt is not None:
            discount_total += max(0.0, amt)
        dtype = str(d.get("type") or d.get("code") or "unknown").strip().lower()
        if dtype:
            types.add(dtype)

    margin_ratio = None
    if list_price is not None and list_price > 0 and paid is not None:
        margin_ratio = paid / list_price
        if margin_ratio <= 0.15:
            _add(
                factors,
                "extreme_margin_erosion",
                30,
                f"paid/list={margin_ratio:.3f}",
            )
        elif margin_ratio <= 0.4:
            _add(
                factors,
                "margin_erosion",
                18,
                f"paid/list={margin_ratio:.3f}",
            )

    if stack_depth >= 3:
        _add(
            factors,
            "promo_stack_depth",
            22 if stack_depth >= 4 else 14,
            f"{stack_depth} discounts stacked ({sorted(types)[:6]})",
        )

    # Incompatible stack: referral + new_user + partner on same redeem
    if len(types & {"referral", "new_user", "partner", "employee", "influencer"}) >= 2:
        _add(
            factors,
            "incompatible_promo_stack",
            20,
            f"stack types {sorted(types)}",
        )

    if redeem_24h is not None and redeem_24h >= 8:
        w = 24 if redeem_24h >= 15 else 14
        _add(
            factors,
            "redeem_velocity",
            w,
            f"redeem_count_24h={redeem_24h}",
        )

    if (
        age is not None
        and age <= 3
        and (
            (margin_ratio is not None and margin_ratio <= 0.5)
            or (redeem_24h is not None and redeem_24h >= 3)
        )
    ):
        _add(
            factors,
            "new_account_promo_burst",
            20,
            f"age_days={age:.0f} with promo aggression",
        )

    # AOV collapse vs list (micro-order farm)
    if aov is not None and list_price is not None and aov <= 15 and stack_depth >= 1:
        _add(
            factors,
            "micro_aov_promo",
            12,
            f"aov_30d={aov:.1f} with discounts",
        )

    # Negative LTV proxy with heavy discount
    if (
        ltv is not None
        and ltv < 0
        and (margin_ratio is not None and margin_ratio <= 0.5)
    ):
        _add(
            factors,
            "negative_ltv_discounted",
            16,
            f"ltv_proxy={ltv:.1f} with eroded margin",
        )

    # Compose loyalty / sibling friction heads (0-1 or 0-100)
    for head, raw in friction.items():
        val = _f(raw)
        if val is None:
            continue
        norm = val / 100.0 if val > 1.0 else val
        if norm >= 0.55:
            h = str(head).strip().lower()
            _add(
                factors,
                f"friction:{h}"[:48],
                min(22.0, 10.0 + norm * 12.0),
                f"friction head {h}={norm:.2f}",
            )

    if block.get("self_referral") is True or block.get("referrer_is_self") is True:
        _add(factors, "self_referral", 28, "Referrer/referee identity collision")

    # Depth factors — code share / first-order / refund-after-promo / geo burst
    same_code_accts = _i(
        block.get("same_code_accounts_24h") or block.get("code_share_accounts_24h")
    )
    if same_code_accts is not None and same_code_accts >= 5:
        _add(
            factors,
            "code_share_farm",
            24 if same_code_accts >= 10 else 16,
            f"same_code_accounts_24h={same_code_accts}",
        )
    first_order = (
        block.get("first_order") is True or block.get("is_first_order") is True
    )
    if first_order and (
        (margin_ratio is not None and margin_ratio <= 0.35)
        or (
            discount_total > 0
            and list_price is not None
            and list_price > 0
            and discount_total / list_price >= 0.6
        )
    ):
        _add(
            factors,
            "first_order_max_discount",
            18,
            "First order with near-max discount",
        )
    geo_burst = _i(
        block.get("geo_redeem_count_24h") or block.get("same_geo_redeems_24h")
    )
    if geo_burst is not None and geo_burst >= 8:
        _add(
            factors,
            "geo_redeem_burst",
            16,
            f"geo_redeem_count_24h={geo_burst}",
        )
    if (
        block.get("refund_after_promo") is True
        or block.get("promo_then_refund") is True
    ):
        _add(
            factors,
            "refund_after_promo",
            22,
            "Promo redeem followed by refund on same order/window",
        )
    device_redeems = _i(block.get("device_redeem_accounts_24h"))
    if device_redeems is not None and device_redeems >= 4:
        _add(
            factors,
            "device_cluster_redeem",
            20,
            f"device_redeem_accounts_24h={device_redeems}",
        )
    if "employee" in types and stack_depth >= 2:
        _add(
            factors,
            "employee_stack_abuse",
            18,
            "Employee discount stacked with other promos",
        )

    score = max(0.0, min(100.0, sum(f.weight for f in factors)))
    tags: list[str] = []
    if factors:
        tags.append("risk:promo_farm")
    codes = {f.code for f in factors}
    if (
        "extreme_margin_erosion" in codes
        or "self_referral" in codes
        or "code_share_farm" in codes
    ):
        tags.append("action:hard_challenge")
    if "redeem_velocity" in codes or "new_account_promo_burst" in codes:
        tags.append("loyalty:friction:step_up")
    if "incompatible_promo_stack" in codes or "promo_stack_depth" in codes:
        tags.append("risk:promo_stack")
    if "refund_after_promo" in codes:
        tags.append("risk:promo_refund_loop")
    if "device_cluster_redeem" in codes or "code_share_farm" in codes:
        tags.append("risk:promo_collusion")

    return PromoEconomicsResult(
        score_0_100=score,
        margin_ratio=margin_ratio,
        stack_depth=stack_depth,
        factors=factors,
        tags=list(dict.fromkeys(tags)),
    )


def apply_promo_economics_features(
    features: dict[str, Any],
    payload: dict[str, Any] | None,
    metadata: dict[str, Any] | None,
) -> dict[str, Any] | None:
    result = compute_promo_economics(payload=payload, metadata=metadata)
    if result is None:
        return None
    features["promo_econ_score"] = round(result.score_0_100, 2)
    features["promo_stack_depth"] = result.stack_depth
    if result.margin_ratio is not None:
        features["promo_margin_ratio"] = round(result.margin_ratio, 4)
    critical = {
        "extreme_margin_erosion",
        "self_referral",
        "redeem_velocity",
        "incompatible_promo_stack",
        "new_account_promo_burst",
        "code_share_farm",
        "refund_after_promo",
        "device_cluster_redeem",
        "first_order_max_discount",
    }
    features["promo_econ_high"] = result.score_0_100 >= 40.0 or any(
        f.code in critical or f.code.startswith("friction:") for f in result.factors
    )
    for f in result.factors:
        features[f"promo_factor:{f.code}"] = True
    return result.evidence()
