"""Seller integrity scores — review-to-delivery ratio monitoring for marketplaces (Prompt 182)."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from typing import Any

DEFAULT_WINDOW_DAYS = 30
DEFAULT_SELLER_LIMIT = 40
HEALTHY_RATIO_MIN = 0.12
HEALTHY_RATIO_MAX = 0.58
WARN_RATIO_ABOVE = 0.85
CRITICAL_RATIO_ABOVE = 1.05


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _review_delivery_ratio(reviews: int, deliveries: int) -> float:
    if deliveries <= 0:
        return float(reviews) if reviews > 0 else 0.0
    return round(reviews / deliveries, 4)


def _score_seller(
    *,
    successful_deliveries: int,
    review_count: int,
) -> tuple[int, str, list[str]]:
    """Return integrity score (0–100), tier, and analyst signals."""
    deliveries = max(0, successful_deliveries)
    reviews = max(0, review_count)
    ratio = _review_delivery_ratio(reviews, deliveries)
    signals: list[str] = []

    if deliveries == 0 and reviews > 0:
        signals.append("reviews_without_deliveries")
        return 8, "critical", signals

    if ratio >= CRITICAL_RATIO_ABOVE:
        signals.append("reviews_exceed_deliveries")
        return max(5, int(15 - (ratio - 1) * 40)), "critical", signals

    if ratio >= WARN_RATIO_ABOVE:
        signals.append("inflated_review_to_delivery_ratio")
        return 32, "warning", signals

    if deliveries >= 80 and ratio < 0.04:
        signals.append("suppressed_review_signal")
        return 52, "warning", signals

    if HEALTHY_RATIO_MIN <= ratio <= HEALTHY_RATIO_MAX:
        return min(98, 88 + int((0.45 - abs(ratio - 0.35)) * 40)), "trusted", signals

    if ratio < HEALTHY_RATIO_MIN and deliveries >= 20:
        signals.append("low_review_engagement")
        return 68, "normal", signals

    return 74, "normal", signals


def _seller_row(index: int, *, tenant_id: str, window_days: int) -> dict[str, Any]:
    seed = hashlib.sha256(f"{tenant_id}:seller_integrity:{index}".encode()).hexdigest()
    bucket = int(seed[0:4], 16)

    # Deterministic cohorts: trusted bulk, warning inflation, critical ghost reviews
    profile = bucket % 7
    if profile == 0:
        deliveries, reviews = 420, 128
    elif profile == 1:
        deliveries, reviews = 310, 98
    elif profile == 2:
        deliveries, reviews = 180, 42
    elif profile == 3:
        deliveries, reviews = 95, 88
    elif profile == 4:
        deliveries, reviews = 60, 72
    elif profile == 5:
        deliveries, reviews = 12, 19
    else:
        deliveries, reviews = 0, 14

    ratio = _review_delivery_ratio(reviews, deliveries)
    score, tier, signals = _score_seller(successful_deliveries=deliveries, review_count=reviews)
    seller_id = f"seller_{seed[:10]}"
    updated = datetime.now(UTC) - timedelta(hours=index * 5.1)

    return {
        "seller_id": seller_id,
        "display_name": f"Marketplace seller {index + 1}",
        "store_slug": f"store-{seed[10:16]}",
        "category": ["electronics", "apparel", "home", "beauty", "grocery"][index % 5],
        "window_days": window_days,
        "successful_deliveries": deliveries,
        "review_count": reviews,
        "review_to_delivery_ratio": ratio,
        "integrity_score": score,
        "integrity_tier": tier,
        "signals": signals,
        "avg_rating": round(3.2 + (int(seed[4:6], 16) % 18) / 10, 1),
        "updated_at": updated.isoformat(),
    }


def build_seller_integrity_payload(
    *,
    tenant_id: str,
    window_days: int = DEFAULT_WINDOW_DAYS,
    limit: int = DEFAULT_SELLER_LIMIT,
) -> dict[str, Any]:
    tid = (tenant_id or "demo").strip() or "demo"
    days = max(7, min(int(window_days), 90))
    lim = max(10, min(int(limit), 200))

    sellers = [_seller_row(i, tenant_id=tid, window_days=days) for i in range(lim)]
    sellers_sorted = sorted(sellers, key=lambda s: (int(s["integrity_score"]), str(s["seller_id"])))

    at_risk = [s for s in sellers if s["integrity_tier"] in ("warning", "critical")]
    ratios = [
        float(s["review_to_delivery_ratio"]) for s in sellers if int(s["successful_deliveries"]) > 0
    ]
    median_ratio = sorted(ratios)[len(ratios) // 2] if ratios else 0.0

    platform_signals: list[str] = []
    critical = sum(1 for s in sellers if s["integrity_tier"] == "critical")
    if critical >= 3:
        platform_signals.append(
            f"{critical} sellers with reviews exceeding or near delivery volume"
        )
    if median_ratio > WARN_RATIO_ABOVE:
        platform_signals.append(
            f"Median review/delivery ratio {median_ratio:.2f} above warn threshold"
        )

    return {
        "tenant_id": tid,
        "updated_at": _now_iso(),
        "source": "demo_aggregate",
        "window_days": days,
        "thresholds": {
            "healthy_ratio_min": HEALTHY_RATIO_MIN,
            "healthy_ratio_max": HEALTHY_RATIO_MAX,
            "warn_ratio_above": WARN_RATIO_ABOVE,
            "critical_ratio_above": CRITICAL_RATIO_ABOVE,
        },
        "summary": {
            "seller_count": len(sellers),
            "at_risk_sellers": len(at_risk),
            "trusted_sellers": sum(1 for s in sellers if s["integrity_tier"] == "trusted"),
            "avg_integrity_score": round(
                sum(int(s["integrity_score"]) for s in sellers) / max(len(sellers), 1),
                1,
            ),
            "median_review_to_delivery_ratio": median_ratio,
            "total_deliveries": sum(int(s["successful_deliveries"]) for s in sellers),
            "total_reviews": sum(int(s["review_count"]) for s in sellers),
        },
        "signals": platform_signals,
        "sellers": sellers_sorted,
    }
