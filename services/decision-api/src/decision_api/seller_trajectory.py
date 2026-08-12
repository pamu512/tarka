"""Seller trajectory changepoint engine — depth over rolling windows (no LIVE).

Host supplies time-ordered metric windows; we detect acceleration, refund-rate
regime shifts, and payout vs GMV divergence. LIVE counters later fill the same
window schema.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

SCHEMA_ID = "tarka.seller_trajectory/v1"
METHOD = "changepoint_heuristic_v1"


@dataclass
class TrajectoryFactor:
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
class TrajectoryResult:
    score_0_100: float
    factors: list[TrajectoryFactor] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    windows_used: int = 0
    seller_id: str | None = None

    def evidence(self) -> dict[str, Any]:
        return {
            "schema_id": SCHEMA_ID,
            "score_0_100": round(self.score_0_100, 2),
            "factors": [f.as_dict() for f in self.factors],
            "tags": list(self.tags),
            "windows_used": self.windows_used,
            "seller_id": self.seller_id,
            "method": METHOD,
            "live_amplification": (
                "Fill windows from warehouse/counters; engine unchanged."
            ),
        }


def _extract(payload: dict[str, Any] | None, metadata: dict[str, Any] | None) -> dict[str, Any] | None:
    for src in (metadata, payload):
        if not isinstance(src, dict):
            continue
        t = src.get("seller_trajectory") or src.get("trajectory")
        if isinstance(t, dict) and isinstance(t.get("windows"), list):
            return t
    return None


def _f(raw: Any) -> float | None:
    try:
        if raw is None or isinstance(raw, bool):
            return None
        return float(raw)
    except (TypeError, ValueError):
        return None


def _norm_windows(raw: list[Any]) -> list[dict[str, float]]:
    out: list[dict[str, float]] = []
    for i, item in enumerate(raw):
        if not isinstance(item, dict):
            continue
        row: dict[str, float] = {"_i": float(i)}
        for key in (
            "gmv",
            "refund_rate",
            "listing_count",
            "payout_amount",
            "order_count",
            "dispute_rate",
            "account_age_days",
        ):
            v = _f(item.get(key))
            if v is not None:
                row[key] = v
        if len(row) > 1:
            out.append(row)
    return out


def _mean(vals: list[float]) -> float | None:
    if not vals:
        return None
    return sum(vals) / len(vals)


def _add(factors: list[TrajectoryFactor], code: str, weight: float, detail: str) -> None:
    if weight <= 0:
        return
    factors.append(
        TrajectoryFactor(code=code, weight=min(36.0, float(weight)), detail=detail)
    )


def compute_seller_trajectory(
    *,
    payload: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
) -> TrajectoryResult | None:
    raw = _extract(payload, metadata)
    if raw is None:
        return None
    windows = _norm_windows(list(raw.get("windows") or []))
    if len(windows) < 3:
        return None

    factors: list[TrajectoryFactor] = []
    seller_id = str(raw.get("seller_id") or "").strip() or None
    n = len(windows)
    split = max(1, n // 2)
    baseline, recent = windows[:split], windows[split:]

    def series(key: str, rows: list[dict[str, float]]) -> list[float]:
        return [r[key] for r in rows if key in r]

    # Refund-rate regime shift
    br = _mean(series("refund_rate", baseline))
    rr = _mean(series("refund_rate", recent))
    if br is not None and rr is not None:
        jump = rr - br
        if jump >= 0.15:
            _add(
                factors,
                "refund_rate_changepoint",
                28 if jump >= 0.25 else 18,
                f"refund_rate baseline={br:.3f} → recent={rr:.3f} (Δ{jump:.3f})",
            )
        if rr >= 0.35:
            _add(
                factors,
                "refund_rate_elevated",
                16,
                f"recent refund_rate {rr:.3f} elevated",
            )

    # GMV acceleration (last vs prior step)
    gmv = series("gmv", windows)
    if len(gmv) >= 3:
        d1 = gmv[-1] - gmv[-2]
        d0 = gmv[-2] - gmv[-3]
        if d1 > 0 and d0 > 0 and d1 >= d0 * 2.5 and d1 >= 500:
            _add(
                factors,
                "gmv_acceleration",
                20,
                f"GMV accel steps Δ={d0:.0f}→{d1:.0f}",
            )

    # Listing velocity spike (depth D)
    listings = series("listing_count", windows)
    ages = series("account_age_days", windows)
    signals = raw.get("signals") if isinstance(raw.get("signals"), dict) else {}
    age = ages[-1] if ages else _f(raw.get("account_age_days"))
    listing_delta = (listings[-1] - listings[0]) if len(listings) >= 2 else 0.0
    listing_step = (
        (listings[-1] - listings[-2]) if len(listings) >= 2 else 0.0
    )
    listing_burst = listing_delta >= 30 or listing_step >= 20
    if listing_delta >= 20 and age is not None and age <= 21:
        _add(
            factors,
            "young_seller_listing_burst",
            22,
            f"listings +{listing_delta:.0f} with age_days={age:.0f}",
        )
    elif listing_burst:
        _add(
            factors,
            "listing_burst",
            18,
            f"listings Δ={listing_delta:.0f} step={listing_step:.0f}",
        )

    # Payout vs GMV divergence (payout accelerating while GMV flat / refunds up)
    payouts = series("payout_amount", windows)
    p_delta = 0.0
    g_delta = 0.0
    if len(payouts) >= 2 and len(gmv) >= 2:
        p_delta = payouts[-1] - payouts[0]
        g_delta = gmv[-1] - gmv[0]
        if p_delta >= 1000 and g_delta <= p_delta * 0.3:
            _add(
                factors,
                "payout_gmv_divergence",
                24,
                f"payout Δ{p_delta:.0f} vs gmv Δ{g_delta:.0f}",
            )

    # Listing burst → cash-out (inventory dump)
    if listing_burst and p_delta >= 800 and g_delta <= p_delta * 0.4:
        _add(
            factors,
            "listing_to_payout_burst",
            26,
            f"listing burst + payout Δ{p_delta:.0f} (gmv Δ{g_delta:.0f})",
        )

    # ATO → payout / destination change (host signals; LIVE device later)
    ato_flag = bool(
        signals.get("ato_recent") is True
        or signals.get("credential_stuffing") is True
        or signals.get("session_anomaly") is True
    )
    reset_h = _f(signals.get("password_reset_hours_ago"))
    if reset_h is not None and reset_h <= 48:
        ato_flag = True
    new_payout_dest = signals.get("new_payout_destination") is True
    recent_payout_step = (
        (payouts[-1] - payouts[-2]) if len(payouts) >= 2 else 0.0
    )
    if ato_flag and (p_delta >= 500 or recent_payout_step >= 400 or new_payout_dest):
        _add(
            factors,
            "ato_then_payout",
            30,
            "ATO/session anomaly near elevated payout"
            + (" + new payout destination" if new_payout_dest else ""),
        )
    elif ato_flag and listing_burst:
        _add(
            factors,
            "ato_then_listing_burst",
            24,
            "ATO/session anomaly with listing burst",
        )

    # Dispute rate rise
    bd = _mean(series("dispute_rate", baseline))
    rd = _mean(series("dispute_rate", recent))
    if bd is not None and rd is not None and (rd - bd) >= 0.1:
        _add(
            factors,
            "dispute_rate_changepoint",
            18,
            f"dispute_rate {bd:.3f}→{rd:.3f}",
        )

    # Order count collapse with refund spike (exit scam pattern)
    orders = series("order_count", windows)
    if len(orders) >= 3 and rr is not None and rr >= 0.2:
        if orders[-1] <= max(1.0, orders[0] * 0.4) and gmv and gmv[-1] < gmv[0]:
            _add(
                factors,
                "exit_scam_shape",
                26,
                "Order/GMV collapse with elevated refunds",
            )

    score = max(0.0, min(100.0, sum(f.weight for f in factors)))
    tags: list[str] = []
    if factors:
        tags.append("risk:seller_trajectory")
    codes = {f.code for f in factors}
    if "refund_rate_changepoint" in codes or "exit_scam_shape" in codes:
        tags.extend(["action:payout_hold", "action:suspend_sales"])
    if "payout_gmv_divergence" in codes or "listing_to_payout_burst" in codes:
        tags.append("action:payout_hold")
    if "young_seller_listing_burst" in codes or "listing_burst" in codes:
        tags.extend(["risk:kyb_unverified_high_volume", "action:kyb_collect"])
    if "ato_then_payout" in codes or "ato_then_listing_burst" in codes:
        tags.extend(
            ["risk:account_takeover", "action:payout_hold", "action:hard_challenge"]
        )

    return TrajectoryResult(
        score_0_100=score,
        factors=factors,
        tags=list(dict.fromkeys(tags)),
        windows_used=n,
        seller_id=seller_id,
    )


def apply_seller_trajectory_features(
    features: dict[str, Any],
    payload: dict[str, Any] | None,
    metadata: dict[str, Any] | None,
) -> dict[str, Any] | None:
    result = compute_seller_trajectory(payload=payload, metadata=metadata)
    if result is None:
        return None
    features["seller_trajectory_score"] = round(result.score_0_100, 2)
    critical = {
        "refund_rate_changepoint",
        "exit_scam_shape",
        "payout_gmv_divergence",
        "young_seller_listing_burst",
        "listing_burst",
        "listing_to_payout_burst",
        "ato_then_payout",
        "ato_then_listing_burst",
    }
    features["seller_trajectory_high"] = result.score_0_100 >= 40.0 or any(
        f.code in critical for f in result.factors
    )
    for f in result.factors:
        features[f"trajectory_factor:{f.code}"] = True
    return result.evidence()
