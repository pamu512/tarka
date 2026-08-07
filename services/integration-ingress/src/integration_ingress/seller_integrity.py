"""Seller integrity scores — review-to-delivery ratio monitoring (Prompt 182, Track B3 durable)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from integration_ingress.seller_integrity_store import list_sellers

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


def _seller_from_row(row: dict[str, Any]) -> dict[str, Any]:
    deliveries = int(row.get("successful_deliveries") or 0)
    reviews = int(row.get("review_count") or 0)
    ratio = _review_delivery_ratio(reviews, deliveries)
    score, tier, signals = _score_seller(successful_deliveries=deliveries, review_count=reviews)
    return {
        "seller_id": row.get("seller_id"),
        "display_name": row.get("display_name") or row.get("seller_id"),
        "store_slug": row.get("store_slug"),
        "category": row.get("category"),
        "window_days": int(row.get("window_days") or DEFAULT_WINDOW_DAYS),
        "successful_deliveries": deliveries,
        "review_count": reviews,
        "review_to_delivery_ratio": ratio,
        "integrity_score": score,
        "integrity_tier": tier,
        "signals": signals,
        "avg_rating": row.get("avg_rating"),
        "updated_at": row.get("updated_at") or _now_iso(),
    }


async def build_seller_integrity_payload(
    session: AsyncSession,
    *,
    tenant_id: str,
    window_days: int = DEFAULT_WINDOW_DAYS,
    limit: int = DEFAULT_SELLER_LIMIT,
) -> dict[str, Any]:
    tid = (tenant_id or "demo").strip() or "demo"
    days = max(7, min(int(window_days), 90))
    lim = max(10, min(int(limit), 200))

    rows = await list_sellers(session, tid, limit=lim)
    sellers = [_seller_from_row(r) for r in rows]
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
        "source": "durable",
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
