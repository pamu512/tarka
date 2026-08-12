"""Order lifecycle sequence risk — depth engine (no LIVE required).

Computes deterministic risk from an ordered checkpoint trail with timestamps,
amounts, roles, and per-stage signals. LIVE vendors later attach richer signals
to the same stages; they do not replace this engine.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

SCHEMA_ID = "tarka.lifecycle_risk/v1"
METHOD = "sequence_heuristic_v1"

# Canonical stage order (unknown stages get large index → treated carefully)
STAGE_ORDER: dict[str, int] = {
    "account_created": 0,
    "listing": 1,
    "checkout": 10,
    "paid": 20,
    "accepted": 25,
    "picked_up": 30,
    "shipped": 35,
    "out_for_delivery": 40,
    "delivered": 50,
    "cancelled": 55,
    "return_started": 58,
    "intake_received": 59,
    "refund_requested": 60,
    "refund_approved": 70,
    "chargeback": 80,
    "payout": 90,
}

# Minimum seconds between checkout/paid and delivered by vertical profile
_DELIVERY_FLOOR_S: dict[str, float] = {
    "marketplace_goods": 30 * 60,
    "food_delivery": 2 * 60,
    "e_hailing": 60,
    "last_mile": 15 * 60,
    "qcommerce": 3 * 60,
}

_COMPLEMENTARY_ROLES: dict[str, frozenset[str]] = {
    "buyer": frozenset({"seller", "courier", "driver"}),
    "rider": frozenset({"driver"}),
    "diner": frozenset({"courier", "merchant", "seller"}),
}


@dataclass
class LifecycleFactor:
    code: str
    weight: float
    detail: str
    stage: str | None = None

    def as_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "code": self.code,
            "weight": round(self.weight, 2),
            "detail": self.detail,
        }
        if self.stage:
            out["stage"] = self.stage
        return out


@dataclass
class LifecycleRiskResult:
    score_0_100: float
    factors: list[LifecycleFactor] = field(default_factory=list)
    driving_stage: str | None = None
    tags: list[str] = field(default_factory=list)
    vertical_profile: str = "marketplace_goods"
    events_scored: int = 0

    def evidence(self) -> dict[str, Any]:
        return {
            "schema_id": SCHEMA_ID,
            "score_0_100": round(self.score_0_100, 2),
            "driving_stage": self.driving_stage,
            "factors": [f.as_dict() for f in self.factors],
            "tags": list(self.tags),
            "vertical_profile": self.vertical_profile,
            "events_scored": self.events_scored,
            "method": METHOD,
            "live_amplification": (
                "Attach vendor spoof/POD/auth signals onto stage.events[].signals; "
                "engine unchanged."
            ),
        }


def _parse_ts(raw: Any) -> datetime | None:
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        try:
            return datetime.fromtimestamp(float(raw), tz=timezone.utc)
        except (OSError, OverflowError, ValueError):
            return None
    if isinstance(raw, str):
        s = raw.strip()
        if not s:
            return None
        try:
            if s.endswith("Z"):
                s = s[:-1] + "+00:00"
            dt = datetime.fromisoformat(s)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except ValueError:
            return None
    return None


def _norm_stage(raw: Any) -> str:
    return str(raw or "").strip().lower().replace(" ", "_").replace("-", "_")


def _norm_role(raw: Any) -> str:
    return str(raw or "").strip().lower()


def _float(raw: Any) -> float | None:
    try:
        if raw is None or isinstance(raw, bool):
            return None
        return float(raw)
    except (TypeError, ValueError):
        return None


def _extract_lifecycle(
    payload: dict[str, Any] | None, metadata: dict[str, Any] | None
) -> dict[str, Any] | None:
    for src in (metadata, payload):
        if not isinstance(src, dict):
            continue
        life = src.get("lifecycle")
        if isinstance(life, dict) and isinstance(life.get("events"), list):
            return life
        # Alternate: top-level lifecycle_events
        ev = src.get("lifecycle_events")
        if isinstance(ev, list):
            return {"events": ev, "order_id": src.get("order_id")}
    return None


def _normalize_events(raw_events: list[Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for item in raw_events:
        if not isinstance(item, dict):
            continue
        stage = _norm_stage(
            item.get("stage") or item.get("checkpoint") or item.get("type")
        )
        if not stage:
            continue
        ts = _parse_ts(item.get("ts") or item.get("timestamp") or item.get("at"))
        signals = item.get("signals") if isinstance(item.get("signals"), dict) else {}
        out.append(
            {
                "stage": stage,
                "ts": ts,
                "amount": _float(item.get("amount")),
                "actor_role": _norm_role(item.get("actor_role") or item.get("role")),
                "actor_id": str(
                    item.get("actor_id") or item.get("entity_id") or ""
                ).strip(),
                "signals": signals,
                "order_idx": int(STAGE_ORDER.get(stage, 1000)),
            }
        )
    # Stable sort: time then canonical order
    out.sort(
        key=lambda e: (
            e["ts"].timestamp() if e["ts"] else 0.0,
            e["order_idx"],
        )
    )
    return out


def _add(
    factors: list[LifecycleFactor],
    code: str,
    weight: float,
    detail: str,
    stage: str | None = None,
) -> None:
    if weight <= 0:
        return
    factors.append(
        LifecycleFactor(
            code=code, weight=min(40.0, float(weight)), detail=detail, stage=stage
        )
    )


def _score_transitions(
    events: list[dict[str, Any]], factors: list[LifecycleFactor]
) -> None:
    stages = [e["stage"] for e in events]
    has = set(stages)

    def first_ts(stage: str) -> datetime | None:
        for e in events:
            if e["stage"] == stage and e["ts"]:
                return e["ts"]
        return None

    delivery_like = bool(has & {"delivered", "picked_up", "out_for_delivery"})
    if "refund_requested" in has and not delivery_like and "intake_received" not in has:
        _add(
            factors,
            "refund_before_delivery",
            28,
            "Refund requested without delivery/pickup stage on trail",
            "refund_requested",
        )
    if "refund_approved" in has and "refund_requested" not in has:
        _add(
            factors,
            "refund_approved_without_request",
            18,
            "Refund approved with no refund_requested stage",
            "refund_approved",
        )
    if "payout" in has and not delivery_like:
        _add(
            factors,
            "payout_before_delivery",
            26,
            "Payout stage before any delivery-like stage",
            "payout",
        )
    if "chargeback" in has and "delivered" in has:
        t_d = first_ts("delivered")
        t_c = first_ts("chargeback")
        if t_d and t_c and (t_c - t_d).total_seconds() < 15 * 60:
            _add(
                factors,
                "chargeback_minutes_after_delivery",
                24,
                "Chargeback within 15m of delivered",
                "chargeback",
            )
    if "cancelled" in has and "delivered" in has:
        t_d = first_ts("delivered")
        t_x = first_ts("cancelled")
        if t_d and t_x and t_x >= t_d and "return_started" not in has:
            _add(
                factors,
                "cancel_after_delivered_no_return",
                22,
                "Cancelled after delivered without return_started",
                "cancelled",
            )
    # Regression: stage index goes backwards (except cancel/refund paths)
    last_idx = -1
    for e in events:
        idx = e["order_idx"]
        if idx >= 1000:
            continue
        if last_idx >= 0 and idx < last_idx - 5:
            # allow cancel/refund branches
            if e["stage"] not in (
                "cancelled",
                "refund_requested",
                "refund_approved",
                "chargeback",
                "return_started",
                "intake_received",
            ):
                _add(
                    factors,
                    "stage_regression",
                    12,
                    f"Stage moved backward to {e['stage']}",
                    e["stage"],
                )
        if e["stage"] not in ("cancelled", "refund_requested", "chargeback"):
            last_idx = max(last_idx, idx)


def _score_time_compression(
    events: list[dict[str, Any]],
    factors: list[LifecycleFactor],
    profile: str,
) -> None:
    floor = _DELIVERY_FLOOR_S.get(profile, _DELIVERY_FLOOR_S["marketplace_goods"])
    start = None
    end = None
    for e in events:
        if e["stage"] in ("checkout", "paid") and e["ts"] and start is None:
            start = e["ts"]
        if e["stage"] in ("delivered",) and e["ts"]:
            end = e["ts"]
    if start and end and end >= start:
        delta = (end - start).total_seconds()
        if delta < floor:
            severity = 30.0 if delta < floor * 0.25 else 18.0
            _add(
                factors,
                "time_compression_delivery",
                severity,
                f"checkout/paid→delivered in {delta:.0f}s (floor {floor:.0f}s for {profile})",
                "delivered",
            )


def _score_amounts(
    events: list[dict[str, Any]], factors: list[LifecycleFactor]
) -> None:
    paid = None
    for e in events:
        if e["stage"] in ("paid", "checkout") and e["amount"] is not None:
            paid = e["amount"]
    if paid is None:
        return
    for e in events:
        if e["stage"] in ("refund_requested", "refund_approved", "chargeback"):
            amt = e["amount"]
            if amt is not None and amt > paid * 1.01:
                _add(
                    factors,
                    "refund_exceeds_paid",
                    20,
                    f"{e['stage']} amount {amt} > paid {paid}",
                    e["stage"],
                )
        if (
            e["stage"] == "payout"
            and e["amount"] is not None
            and e["amount"] > paid * 1.15
        ):
            _add(
                factors,
                "payout_exceeds_order",
                16,
                f"payout {e['amount']} >> paid {paid}",
                "payout",
            )


def _score_signals(
    events: list[dict[str, Any]], factors: list[LifecycleFactor]
) -> None:
    for e in events:
        sig = e["signals"]
        stage = e["stage"]
        if sig.get("pod_hash_ok") is False or sig.get("delivery_hash_mismatch") is True:
            _add(
                factors,
                "pod_hash_mismatch",
                22,
                "POD/delivery hash failed on stage",
                stage,
            )
        if sig.get("intake_ok") is False or sig.get("ftid_intake_mismatch") is True:
            _add(
                factors,
                "ftid_intake_mismatch",
                30,
                "Intake mismatch on return/refund path",
                stage,
            )
        if sig.get("gps_spoof") is True or sig.get("is_location_spoof") is True:
            _add(
                factors,
                "gps_spoof_on_stage",
                24,
                "Location spoof signal on lifecycle stage",
                stage,
            )
        if sig.get("worker_auth_failed") is True:
            _add(
                factors,
                "worker_auth_failed",
                26,
                "Worker auth failed during stage",
                stage,
            )


def _score_role_clash(
    events: list[dict[str, Any]], factors: list[LifecycleFactor]
) -> None:
    by_actor: dict[str, set[str]] = {}
    for e in events:
        aid = e["actor_id"]
        role = e["actor_role"]
        if not aid or not role:
            continue
        by_actor.setdefault(aid, set()).add(role)
    for aid, roles in by_actor.items():
        for r in roles:
            comps = _COMPLEMENTARY_ROLES.get(r, frozenset())
            clash = roles & comps
            if clash:
                _add(
                    factors,
                    "cross_role_same_actor",
                    34,
                    f"Actor {aid[:32]} holds roles {sorted(roles)} on one order",
                    None,
                )
                break


def _first_ts(events: list[dict[str, Any]], stage: str) -> datetime | None:
    for e in events:
        if e["stage"] == stage and e["ts"]:
            return e["ts"]
    return None


def _score_sequence_depth(
    events: list[dict[str, Any]],
    factors: list[LifecycleFactor],
    profile: str,
) -> None:
    """Deeper vertical sequence detections beyond core transitions."""
    stages = [e["stage"] for e in events]
    has = set(stages)
    cancel_n = stages.count("cancelled")
    refund_n = stages.count("refund_requested")

    if "paid" in has and "checkout" not in has:
        _add(
            factors,
            "paid_without_checkout",
            14,
            "Paid stage with no checkout on trail",
            "paid",
        )

    if "chargeback" in has and "delivered" not in has and "picked_up" not in has:
        _add(
            factors,
            "chargeback_without_delivery",
            26,
            "Chargeback without delivery/pickup stage",
            "chargeback",
        )

    if refund_n >= 2:
        _add(
            factors,
            "multi_refund_attempt",
            20,
            f"refund_requested appears {refund_n} times on trail",
            "refund_requested",
        )

    if "refund_requested" in has and "refund_approved" in has:
        t_req = _first_ts(events, "refund_requested")
        t_apr = _first_ts(events, "refund_approved")
        if t_req and t_apr and (t_apr - t_req).total_seconds() < 60:
            _add(
                factors,
                "instant_refund_approval",
                18,
                "Refund approved within 60s of request",
                "refund_approved",
            )

    # Food: cancel after pickup / rapid cancel→refund
    if profile == "food_delivery":
        if "cancelled" in has and "picked_up" in has and "delivered" not in has:
            t_p = _first_ts(events, "picked_up")
            t_c = _first_ts(events, "cancelled")
            if t_p and t_c and t_c >= t_p:
                _add(
                    factors,
                    "cancel_after_pickup",
                    24,
                    "Cancelled after pickup without delivered",
                    "cancelled",
                )
        if "cancelled" in has and "refund_requested" in has:
            t_c = _first_ts(events, "cancelled")
            t_r = _first_ts(events, "refund_requested")
            if t_c and t_r and 0 <= (t_r - t_c).total_seconds() <= 5 * 60:
                _add(
                    factors,
                    "rapid_cancel_refund",
                    22,
                    "Refund within 5m of cancel",
                    "refund_requested",
                )

    # E-hailing: cancel storm / cancel right after accept / spoof / surge farm
    if profile == "e_hailing":
        if cancel_n >= 2:
            _add(
                factors,
                "cancel_storm",
                24,
                f"{cancel_n} cancel stages on one trip trail",
                "cancelled",
            )
        if "accepted" in has and "cancelled" in has:
            t_a = _first_ts(events, "accepted")
            t_c = _first_ts(events, "cancelled")
            if t_a and t_c and 0 <= (t_c - t_a).total_seconds() <= 90:
                _add(
                    factors,
                    "cancel_seconds_after_accept",
                    20,
                    "Cancelled within 90s of accepted",
                    "cancelled",
                )
        for e in events:
            sig = e.get("signals") or {}
            if sig.get("gps_spoof") is True or sig.get("location_spoof") is True:
                _add(
                    factors,
                    "gps_spoof_on_stage",
                    28,
                    f"GPS/location spoof signal on stage {e['stage']}",
                    e["stage"],
                )
            if sig.get("fake_surge") is True or sig.get("surge_manipulation") is True:
                _add(
                    factors,
                    "fake_surge_signal",
                    22,
                    f"Surge manipulation signal on stage {e['stage']}",
                    e["stage"],
                )
            bonus_claims = sig.get("bonus_claim_count_24h") or sig.get(
                "incentive_claims_24h"
            )
            try:
                bc = int(bonus_claims) if bonus_claims is not None else None
            except (TypeError, ValueError):
                bc = None
            if bc is not None and bc >= 8:
                _add(
                    factors,
                    "incentive_claim_farm",
                    20,
                    f"bonus_claim_count_24h={bc}",
                    e["stage"],
                )

    # Last-mile / COD: refusal signal or accept→cancel without delivery
    if profile in ("last_mile", "logistics"):
        for e in events:
            sig = e.get("signals") or {}
            if sig.get("cod_refused") is True or sig.get("cod_refusal") is True:
                _add(
                    factors,
                    "cod_refuse_on_stage",
                    22,
                    "COD refusal signal on lifecycle stage",
                    e["stage"],
                )
        if "accepted" in has and "cancelled" in has and "delivered" not in has:
            _add(
                factors,
                "accept_cancel_no_delivery",
                18,
                "Accepted then cancelled with no delivery (fake-order pattern)",
                "cancelled",
            )


def _tags_from_factors(factors: list[LifecycleFactor]) -> list[str]:
    tags = ["risk:lifecycle"]
    codes = {f.code for f in factors}
    if "refund_before_delivery" in codes or "ftid_intake_mismatch" in codes:
        tags.append("action:refund_hold")
        tags.append("risk:ftid")
    if "pod_hash_mismatch" in codes:
        tags.append("risk:refund_burst")
        tags.append("risk:friendly_fraud")
    if "cross_role_same_actor" in codes or "gps_spoof_on_stage" in codes:
        tags.append("risk:collusion_shared_device")
        tags.append("action:hard_challenge")
    if (
        "chargeback_minutes_after_delivery" in codes
        or "chargeback_without_delivery" in codes
    ):
        tags.append("risk:friendly_fraud")
        tags.append("action:dispute_open")
    if "payout_before_delivery" in codes or "payout_exceeds_order" in codes:
        tags.append("action:payout_hold")
    if "time_compression_delivery" in codes:
        tags.append("risk:courier_spoof")
    if "cancel_after_pickup" in codes or "rapid_cancel_refund" in codes:
        tags.append("risk:refund_burst")
        tags.append("action:hard_challenge")
    if "cancel_storm" in codes or "cancel_seconds_after_accept" in codes:
        tags.append("risk:refund_burst")
        tags.append("action:hard_challenge")
    if "fake_surge_signal" in codes or "incentive_claim_farm" in codes:
        tags.append("risk:incentive_abuse")
        tags.append("action:hard_challenge")
    if "gps_spoof_on_stage" in codes:
        tags.append("risk:courier_spoof")
    if "cod_refuse_on_stage" in codes or "accept_cancel_no_delivery" in codes:
        tags.append("risk:cod_abuse")
        tags.append("action:hard_challenge")
    if "multi_refund_attempt" in codes or "instant_refund_approval" in codes:
        tags.append("risk:refund_burst")
        tags.append("action:refund_hold")
    return list(dict.fromkeys(tags))


def compute_lifecycle_risk(
    *,
    payload: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
    vertical_profile: str | None = None,
) -> LifecycleRiskResult | None:
    """Return risk result or None when no usable lifecycle trail."""
    life = _extract_lifecycle(payload, metadata)
    if life is None:
        return None
    events = _normalize_events(list(life.get("events") or []))
    if len(events) < 2:
        return None

    profile = (
        vertical_profile or life.get("vertical_profile") or life.get("profile") or ""
    ).strip().lower() or "marketplace_goods"
    if profile in ("marketplace", "goods"):
        profile = "marketplace_goods"
    if profile in ("food", "delivery"):
        profile = "food_delivery"
    if profile in ("ride_hailing", "ehailing"):
        profile = "e_hailing"
    if profile in ("logistics", "cod", "lastmile"):
        profile = "last_mile"

    factors: list[LifecycleFactor] = []
    _score_transitions(events, factors)
    _score_time_compression(events, factors, profile)
    _score_amounts(events, factors)
    _score_signals(events, factors)
    _score_role_clash(events, factors)
    _score_sequence_depth(events, factors, profile)

    raw = sum(f.weight for f in factors)
    score = max(0.0, min(100.0, raw))
    # Cap diminishing returns slightly when many weak factors
    if len(factors) >= 4 and score < 95:
        score = min(100.0, score * 0.92 + 8.0)

    driving = None
    if factors:
        driving = (
            max(factors, key=lambda f: f.weight).stage
            or max(factors, key=lambda f: f.weight).code
        )

    tags = _tags_from_factors(factors) if factors else []
    return LifecycleRiskResult(
        score_0_100=score,
        factors=factors,
        driving_stage=driving,
        tags=tags,
        vertical_profile=profile,
        events_scored=len(events),
    )


def apply_lifecycle_risk_features(
    features: dict[str, Any],
    payload: dict[str, Any] | None,
    metadata: dict[str, Any] | None,
    *,
    vertical_profile: str | None = None,
) -> dict[str, Any] | None:
    """Mutate features; return evidence dict or None."""
    result = compute_lifecycle_risk(
        payload=payload, metadata=metadata, vertical_profile=vertical_profile
    )
    if result is None:
        return None
    features["lifecycle_risk_score"] = round(result.score_0_100, 2)
    _critical = {
        "refund_before_delivery",
        "ftid_intake_mismatch",
        "cross_role_same_actor",
        "payout_before_delivery",
        "chargeback_minutes_after_delivery",
        "chargeback_without_delivery",
        "cancel_after_pickup",
        "rapid_cancel_refund",
        "cancel_storm",
        "multi_refund_attempt",
        "cod_refuse_on_stage",
        "gps_spoof_on_stage",
        "fake_surge_signal",
        "incentive_claim_farm",
    }
    features["lifecycle_risk_high"] = result.score_0_100 >= 40.0 or any(
        f.code in _critical for f in result.factors
    )
    if result.driving_stage:
        features["lifecycle_driving_stage"] = result.driving_stage
    for f in result.factors:
        # Expose strong factor codes as features for packs
        features[f"lifecycle_factor:{f.code}"] = True
    return result.evidence()
