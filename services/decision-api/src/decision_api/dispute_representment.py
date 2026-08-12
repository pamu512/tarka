"""Dispute representment strength — evidence completeness vs reason code.

Scores whether the merchant evidence pack is strong enough to fight a
chargeback/dispute. No card-network LIVE required; Ethoca/Verifi alerts
feed the same reason_code + evidence flags.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

SCHEMA_ID = "tarka.dispute_representment/v1"
METHOD = "evidence_matrix_v1"

# Reason-code → required evidence dimensions (True = required for strong pack)
_REQUIREMENTS: dict[str, dict[str, bool]] = {
    "4853": {
        "pod": True,
        "tracking": True,
        "chat": False,
        "id_check": False,
        "avs": False,
        "3ds": False,
    },
    "4855": {
        "pod": True,
        "tracking": True,
        "chat": True,
        "id_check": False,
        "avs": False,
        "3ds": False,
    },
    "4860": {
        "pod": False,
        "tracking": False,
        "chat": True,
        "id_check": True,
        "avs": True,
        "3ds": False,
    },
    "4837": {
        "pod": True,
        "tracking": True,
        "chat": False,
        "id_check": True,
        "avs": True,
        "3ds": True,
    },
    "13.1": {
        "pod": True,
        "tracking": True,
        "chat": False,
        "id_check": False,
        "avs": False,
        "3ds": False,
    },
    "10.4": {
        "pod": True,
        "tracking": True,
        "chat": True,
        "id_check": False,
        "avs": False,
        "3ds": False,
    },
    "default": {
        "pod": True,
        "tracking": True,
        "chat": False,
        "id_check": False,
        "avs": False,
        "3ds": False,
    },
}


@dataclass
class DisputeFactor:
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
class RepresentmentResult:
    strength_0_100: float
    """High = strong merchant position (inverse of risk)."""

    risk_0_100: float
    """High = weak pack / likely loss."""

    missing: list[str] = field(default_factory=list)
    factors: list[DisputeFactor] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    reason_code: str = ""

    def evidence(self) -> dict[str, Any]:
        return {
            "schema_id": SCHEMA_ID,
            "strength_0_100": round(self.strength_0_100, 2),
            "risk_0_100": round(self.risk_0_100, 2),
            "missing_evidence": list(self.missing),
            "factors": [f.as_dict() for f in self.factors],
            "tags": list(self.tags),
            "reason_code": self.reason_code,
            "method": METHOD,
            "live_amplification": (
                "Chargeback alert connector supplies reason_code; case-api "
                "evidence bundle fills has_* flags."
            ),
        }


def _truthy(v: Any) -> bool:
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return bool(v)
    if isinstance(v, str):
        return v.strip().lower() in ("1", "true", "yes", "y")
    return False


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


def _extract(payload: dict[str, Any] | None, metadata: dict[str, Any] | None) -> dict[str, Any] | None:
    for src in (metadata, payload):
        if not isinstance(src, dict):
            continue
        block = (
            src.get("dispute_evidence")
            or src.get("representment")
            or src.get("dispute_representment")
        )
        if isinstance(block, dict):
            return block
    return None


def _add(factors: list[DisputeFactor], code: str, weight: float, detail: str) -> None:
    factors.append(DisputeFactor(code=code, weight=min(36.0, weight), detail=detail))


def compute_representment_strength(
    *,
    payload: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
) -> RepresentmentResult | None:
    block = _extract(payload, metadata)
    if block is None:
        return None

    reason = str(block.get("reason_code") or block.get("code") or "default").strip()
    req = _REQUIREMENTS.get(reason) or _REQUIREMENTS["default"]

    has = {
        "pod": _truthy(
            block.get("has_pod")
            or block.get("pod")
            or block.get("proof_of_delivery")
        ),
        "tracking": _truthy(block.get("has_tracking") or block.get("tracking")),
        "chat": _truthy(block.get("has_chat") or block.get("chat_log")),
        "id_check": _truthy(block.get("has_id_check") or block.get("id_verified")),
        "avs": _truthy(block.get("has_avs") or block.get("avs_match")),
        "3ds": _truthy(block.get("has_3ds") or block.get("three_ds") or block.get("3ds")),
    }

    factors: list[DisputeFactor] = []
    missing: list[str] = []
    strength = 100.0

    for dim, required in req.items():
        if not required:
            if has.get(dim):
                strength += 0  # already at cap path — bonus below
            continue
        if not has.get(dim):
            missing.append(dim)
            penalty = 22.0 if dim in ("pod", "tracking") else 14.0
            strength -= penalty
            _add(
                factors,
                f"missing_{dim}",
                penalty,
                f"Required evidence '{dim}' absent for reason {reason}",
            )
        else:
            strength = min(100.0, strength + 0)  # present — no penalty

    # Bonuses for optional present evidence
    for dim, required in req.items():
        if not required and has.get(dim):
            strength = min(100.0, strength + 6.0)

    prior_won = _i(block.get("prior_won")) or 0
    prior_lost = _i(block.get("prior_lost")) or 0
    prior_total = prior_won + prior_lost
    if prior_total >= 3:
        win_rate = prior_won / prior_total
        if win_rate <= 0.35:
            strength -= 18
            _add(
                factors,
                "weak_prior_win_rate",
                18,
                f"prior win_rate={win_rate:.2f} n={prior_total}",
            )
        elif win_rate >= 0.7:
            strength = min(100.0, strength + 8.0)

    amount = _f(block.get("amount"))
    if amount is not None and amount >= 500 and missing:
        strength -= 10
        _add(
            factors,
            "high_amount_incomplete_pack",
            10,
            f"amount={amount:.0f} with missing {missing}",
        )

    hours = _f(block.get("hours_to_deadline"))
    if hours is not None and hours <= 24 and missing:
        strength -= 12
        _add(
            factors,
            "deadline_pressure_incomplete",
            12,
            f"{hours:.0f}h to deadline with gaps",
        )

    # Depth factors — alert timing, serial disputer, claim conflicts
    if prior_lost >= 3:
        strength -= 14
        _add(
            factors,
            "serial_disputer",
            14,
            f"prior_lost={prior_lost} (serial dispute pattern)",
        )
    alert_hours = _f(block.get("hours_since_alert") or block.get("alert_age_hours"))
    if alert_hours is not None and alert_hours >= 48 and missing:
        strength -= 10
        _add(
            factors,
            "stale_alert_incomplete_pack",
            10,
            f"alert {alert_hours:.0f}h old with evidence gaps",
        )
    if _truthy(block.get("early_alert") or block.get("chargeback_early_alert")) and (
        not has.get("pod") or not has.get("tracking")
    ):
        strength -= 12
        _add(
            factors,
            "early_alert_no_fulfillment_evidence",
            12,
            "Ethoca/Verifi-style early alert without POD/tracking",
        )
    claim = str(block.get("cardholder_claim") or block.get("claim") or "").strip().lower()
    if claim in ("not_received", "not delivered", "merchandise_not_received") and has.get(
        "pod"
    ):
        # Merchant-favorable: claim conflicts with POD — raise strength only
        strength = min(100.0, strength + 10.0)
    if _truthy(block.get("no_auth") or block.get("fraud_claim")) and not has.get("3ds"):
        strength -= 10
        _add(
            factors,
            "fraud_claim_missing_3ds",
            10,
            "Fraud/no-auth claim without 3DS evidence",
        )

    strength = max(0.0, min(100.0, strength))
    risk = round(100.0 - strength, 2)

    tags: list[str] = ["risk:dispute_representment"]
    if risk >= 45 or missing:
        tags.append("action:dispute_evidence_gap")
    if risk >= 60:
        tags.extend(["risk:friendly_fraud", "action:refund_hold"])
    if any(f.code == "serial_disputer" for f in factors):
        tags.append("risk:serial_disputer")
    if any(f.code == "early_alert_no_fulfillment_evidence" for f in factors):
        tags.append("risk:chargeback_alert_gap")
    if strength >= 80 and not missing:
        tags.append("dispute:strong_pack")

    return RepresentmentResult(
        strength_0_100=strength,
        risk_0_100=risk,
        missing=missing,
        factors=factors,
        tags=list(dict.fromkeys(tags)),
        reason_code=reason,
    )


def apply_representment_features(
    features: dict[str, Any],
    payload: dict[str, Any] | None,
    metadata: dict[str, Any] | None,
) -> dict[str, Any] | None:
    result = compute_representment_strength(payload=payload, metadata=metadata)
    if result is None:
        return None
    features["representment_strength"] = round(result.strength_0_100, 2)
    features["representment_risk"] = round(result.risk_0_100, 2)
    features["representment_weak"] = result.risk_0_100 >= 45.0 or bool(result.missing)
    features["representment_missing_count"] = len(result.missing)
    for m in result.missing:
        features[f"representment_missing:{m}"] = True
    for f in result.factors:
        features[f"representment_factor:{f.code}"] = True
    return result.evidence()
