"""Live-commerce / listing risk — host metadata depth (no DIY crawl / no LIVE).

Brand-protection connector hits feed the same schema; OSS heuristics cover
price anomalies, thin media, new-seller live streams, and counterfeit flags.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

SCHEMA_ID = "tarka.listing_risk/v1"
METHOD = "listing_heuristic_v1"


@dataclass
class ListingFactor:
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
class ListingRiskResult:
    score_0_100: float
    factors: list[ListingFactor] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)

    def evidence(self) -> dict[str, Any]:
        return {
            "schema_id": SCHEMA_ID,
            "score_0_100": round(self.score_0_100, 2),
            "factors": [f.as_dict() for f in self.factors],
            "tags": list(self.tags),
            "method": METHOD,
            "live_claim_allowed": False,
            "live_amplification": (
                "Brand-protection connector sets brand_protection_hit; "
                "host fills listing_* fields from catalog/live-stream."
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


def _truthy(v: Any) -> bool:
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return bool(v)
    if isinstance(v, str):
        return v.strip().lower() in ("1", "true", "yes", "y")
    return False


def _extract(
    payload: dict[str, Any] | None, metadata: dict[str, Any] | None
) -> dict[str, Any] | None:
    for src in (metadata, payload):
        if not isinstance(src, dict):
            continue
        block = src.get("listing_risk") or src.get("listing")
        if isinstance(block, dict):
            return block
    return None


def _add(factors: list[ListingFactor], code: str, weight: float, detail: str) -> None:
    if weight <= 0:
        return
    factors.append(ListingFactor(code=code, weight=min(36.0, weight), detail=detail))


def compute_listing_risk(
    *,
    payload: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
) -> ListingRiskResult | None:
    block = _extract(payload, metadata)
    if block is None:
        return None

    # Need at least one discriminative field
    keys = (
        "live_stream",
        "brand_protection_hit",
        "counterfeit_keyword_hit",
        "price_vs_category_median_ratio",
        "image_count",
        "listing_age_hours",
        "seller_account_age_days",
        "concurrent_viewers",
        "listing_count_24h",
    )
    if not any(k in block for k in keys):
        return None

    factors: list[ListingFactor] = []
    live = _truthy(block.get("live_stream"))
    brand_hit = _truthy(block.get("brand_protection_hit"))
    kw_hit = _truthy(block.get("counterfeit_keyword_hit"))
    price_ratio = _f(block.get("price_vs_category_median_ratio"))
    images = _i(block.get("image_count"))
    listing_age_h = _f(block.get("listing_age_hours"))
    seller_age = _f(block.get("seller_account_age_days"))
    viewers = _i(block.get("concurrent_viewers"))
    listing_burst = _i(block.get("listing_count_24h"))

    if brand_hit:
        _add(factors, "brand_protection_hit", 32, "Brand-protection connector/host hit")
    if kw_hit:
        _add(factors, "counterfeit_keyword_hit", 22, "Host counterfeit keyword flag")

    if price_ratio is not None and price_ratio <= 0.25:
        _add(
            factors,
            "price_anomaly_low",
            24 if price_ratio <= 0.12 else 16,
            f"price/category_median={price_ratio:.3f}",
        )

    if images is not None and images <= 1:
        _add(factors, "thin_listing_media", 12, f"image_count={images}")

    if live and seller_age is not None and seller_age <= 14:
        _add(
            factors,
            "live_stream_new_seller",
            26,
            f"Live stream with seller_age_days={seller_age:.0f}",
        )
    elif (
        live
        and listing_age_h is not None
        and listing_age_h <= 2
        and (viewers is not None and viewers >= 200)
    ):
        _add(
            factors,
            "live_stream_burst_viewers",
            18,
            f"Live listing age_h={listing_age_h:.1f} viewers={viewers}",
        )

    if (
        listing_burst is not None
        and listing_burst >= 25
        and (seller_age is not None and seller_age <= 21)
    ):
        _add(
            factors,
            "young_seller_listing_flood",
            20,
            f"listing_count_24h={listing_burst} age_days={seller_age:.0f}",
        )

    if not factors:
        return None

    score = max(0.0, min(100.0, sum(f.weight for f in factors)))
    tags = ["risk:listing"]
    codes = {f.code for f in factors}
    if "brand_protection_hit" in codes or "counterfeit_keyword_hit" in codes:
        tags.extend(["risk:counterfeit", "action:listing_takedown"])
    if "live_stream_new_seller" in codes or "live_stream_burst_viewers" in codes:
        tags.extend(["risk:live_commerce", "action:hard_challenge"])
    if "price_anomaly_low" in codes:
        tags.append("risk:counterfeit")
    if "young_seller_listing_flood" in codes:
        tags.extend(["action:kyb_collect", "action:suspend_sales"])

    return ListingRiskResult(
        score_0_100=score,
        factors=factors,
        tags=list(dict.fromkeys(tags)),
    )


def apply_listing_risk_features(
    features: dict[str, Any],
    payload: dict[str, Any] | None,
    metadata: dict[str, Any] | None,
) -> dict[str, Any] | None:
    result = compute_listing_risk(payload=payload, metadata=metadata)
    if result is None:
        return None
    features["listing_risk_score"] = round(result.score_0_100, 2)
    critical = {
        "brand_protection_hit",
        "live_stream_new_seller",
        "price_anomaly_low",
        "young_seller_listing_flood",
        "counterfeit_keyword_hit",
    }
    features["listing_risk_high"] = result.score_0_100 >= 40.0 or any(
        f.code in critical for f in result.factors
    )
    if any(f.code == "brand_protection_hit" for f in result.factors):
        features["brand_protection_hit"] = True
    for f in result.factors:
        features[f"listing_factor:{f.code}"] = True
    return result.evidence()
