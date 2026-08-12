"""FTID causal intake gate — Downstream fields only (no carrier APIs).

State machine over delivery → intake → mismatch taxonomy → hold/release.
LIVE returns platforms later webhook into the same field schema.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

SCHEMA_ID = "tarka.ftid_intake_gate/v1"
METHOD = "causal_fsm_v1"

# FSM states
STATES = (
    "no_return",
    "carrier_delivered",
    "intake_pending",
    "intake_matched",
    "mismatch_hash",
    "mismatch_weight",
    "mismatch_label",
    "mismatch_empty_box",
    "mismatch_missing_intake",
    "refund_held",
    "refund_releasable",
)


@dataclass
class FtidFactor:
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
class FtidGateResult:
    state: str
    refund_hold: bool
    mismatch_class: str | None
    score_0_100: float
    factors: list[FtidFactor] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)

    def evidence(self) -> dict[str, Any]:
        return {
            "schema_id": SCHEMA_ID,
            "state": self.state,
            "refund_hold": self.refund_hold,
            "mismatch_class": self.mismatch_class,
            "score_0_100": round(self.score_0_100, 2),
            "factors": [f.as_dict() for f in self.factors],
            "tags": list(self.tags),
            "method": METHOD,
            "live_amplification": (
                "Loop-class / WMS webhooks populate the same boolean fields."
            ),
        }


def _truthy(v: Any) -> bool | None:
    if isinstance(v, bool):
        return v
    if v is None:
        return None
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return bool(v)
    if isinstance(v, str):
        s = v.strip().lower()
        if s in ("1", "true", "yes", "y"):
            return True
        if s in ("0", "false", "no", "n"):
            return False
    return None


def _f(v: Any) -> float | None:
    try:
        if v is None or isinstance(v, bool):
            return None
        return float(v)
    except (TypeError, ValueError):
        return None


def _extract(payload: dict[str, Any] | None, metadata: dict[str, Any] | None) -> dict[str, Any] | None:
    for src in (metadata, payload):
        if not isinstance(src, dict):
            continue
        block = src.get("ftid") or src.get("return_intake") or src.get("ftid_intake")
        if isinstance(block, dict):
            return block
    return None


def _add(factors: list[FtidFactor], code: str, weight: float, detail: str) -> None:
    factors.append(FtidFactor(code=code, weight=min(40.0, weight), detail=detail))


def compute_ftid_gate(
    *,
    payload: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
) -> FtidGateResult | None:
    block = _extract(payload, metadata)
    if block is None:
        return None

    carrier_delivered = _truthy(block.get("carrier_delivered"))
    intake_received = _truthy(block.get("intake_received"))
    refund_requested = _truthy(block.get("refund_requested"))
    # If none of the core flags present, not an FTID evaluation
    if (
        carrier_delivered is None
        and intake_received is None
        and refund_requested is None
        and block.get("intake_hash_ok") is None
    ):
        return None

    hash_ok = _truthy(block.get("intake_hash_ok"))
    weight_ok = _truthy(block.get("weight_ok"))
    label_ok = _truthy(block.get("label_ok"))
    photo_ok = _truthy(block.get("photo_hash_ok"))
    empty_box = _truthy(block.get("empty_box_suspected"))
    hours = _f(block.get("hours_since_delivered"))
    serial_returns = _f(block.get("prior_return_count_90d") or block.get("serial_return_count"))
    refund_amt = _f(block.get("refund_amount") or block.get("amount"))
    item_value = _f(block.get("declared_item_value") or block.get("item_value"))
    swap_hint = _truthy(block.get("item_swap_suspected") or block.get("swap_suspected"))

    factors: list[FtidFactor] = []
    state = "no_return"
    mismatch: str | None = None
    failures: list[str] = []

    if carrier_delivered is True:
        state = "carrier_delivered"

    if refund_requested is True and carrier_delivered is True:
        if intake_received is not True:
            state = "mismatch_missing_intake"
            mismatch = "missing_intake"
            _add(
                factors,
                "refund_without_intake",
                34,
                "Refund requested after carrier delivered but intake not received",
            )
        else:
            state = "intake_pending"
            # Evaluate match dimensions
            if hash_ok is False:
                failures.append("hash")
                _add(factors, "intake_hash_mismatch", 30, "Intake hash mismatch")
            if weight_ok is False:
                failures.append("weight")
                _add(factors, "intake_weight_mismatch", 26, "Intake weight mismatch")
            if label_ok is False:
                failures.append("label")
                _add(factors, "intake_label_mismatch", 24, "Intake label mismatch")
            if photo_ok is False:
                failures.append("photo")
                _add(factors, "intake_photo_mismatch", 18, "Intake photo hash mismatch")
            if empty_box is True:
                failures.append("empty_box")
                _add(factors, "empty_box_suspected", 32, "Empty-box / FTID suspected")

            if failures:
                # Priority taxonomy
                priority = (
                    "empty_box"
                    if "empty_box" in failures
                    else "hash"
                    if "hash" in failures
                    else "weight"
                    if "weight" in failures
                    else "label"
                    if "label" in failures
                    else "photo"
                )
                mismatch = priority
                state = f"mismatch_{priority}" if priority != "photo" else "mismatch_hash"
                if priority == "photo":
                    state = "mismatch_hash"
            else:
                # All known checks ok (or unset — treat unset as not failing)
                if hash_ok is True or weight_ok is True or label_ok is True:
                    state = "intake_matched"
                elif hash_ok is None and weight_ok is None and label_ok is None:
                    # Intake received but no verification fields — pending
                    state = "intake_pending"
                    _add(
                        factors,
                        "intake_unverified",
                        12,
                        "Intake received without verification dimensions",
                    )
                else:
                    state = "intake_matched"

    elif refund_requested is True and carrier_delivered is not True:
        # Refund without carrier delivery scan — different abuse class
        _add(
            factors,
            "refund_without_delivery_scan",
            20,
            "Refund requested without carrier_delivered=true",
        )
        state = "intake_pending"

    # Stale delivered without intake while refund open
    if (
        carrier_delivered is True
        and intake_received is not True
        and refund_requested is True
        and hours is not None
        and hours >= 72
    ):
        _add(
            factors,
            "stale_delivered_no_intake",
            16,
            f"{hours:.0f}h since delivered with no intake",
        )

    # Depth factors (taxonomy expansion — Downstream fields only)
    if len(failures) >= 2:
        _add(
            factors,
            "multi_dimension_mismatch",
            18,
            f"{len(failures)} intake dimensions failed: {failures}",
        )
    if (
        ("hash" in failures and "weight" in failures)
        or swap_hint is True
    ):
        _add(
            factors,
            "item_swap_suspected",
            28,
            "Hash+weight fail or host swap flag — possible item swap",
        )
    if serial_returns is not None and serial_returns >= 3 and refund_requested is True:
        _add(
            factors,
            "serial_returner",
            22,
            f"prior_return_count_90d={serial_returns:.0f}",
        )
    if (
        refund_amt is not None
        and item_value is not None
        and item_value > 0
        and refund_amt >= item_value * 1.5
        and refund_requested is True
    ):
        _add(
            factors,
            "refund_over_declared_value",
            16,
            f"refund={refund_amt:.0f} vs declared={item_value:.0f}",
        )
    if (
        refund_requested is True
        and carrier_delivered is True
        and hours is not None
        and hours <= 6
    ):
        _add(
            factors,
            "instant_refund_after_delivery",
            14,
            f"refund within {hours:.1f}h of delivery scan",
        )

    score = max(0.0, min(100.0, sum(f.weight for f in factors)))
    hold = state.startswith("mismatch_") or any(
        f.code
        in (
            "refund_without_intake",
            "empty_box_suspected",
            "intake_hash_mismatch",
            "item_swap_suspected",
            "multi_dimension_mismatch",
        )
        for f in factors
    )
    if hold:
        state = "refund_held" if not state.startswith("mismatch_") else state
        # keep mismatch state for taxonomy; refund_hold flag is source of truth
    elif state == "intake_matched" and refund_requested is True:
        state = "refund_releasable"

    tags: list[str] = []
    if factors:
        tags.append("risk:ftid")
    if hold:
        tags.extend(["action:refund_hold", "risk:ftid"])
    if mismatch == "empty_box" or any(
        f.code == "item_swap_suspected" for f in factors
    ):
        tags.append("risk:friendly_fraud")
    if any(f.code == "serial_returner" for f in factors):
        tags.append("risk:serial_returner")
    if state == "refund_releasable":
        tags.append("ftid:releasable")

    return FtidGateResult(
        state=state if state in STATES or state.startswith("mismatch_") else "intake_pending",
        refund_hold=hold,
        mismatch_class=mismatch,
        score_0_100=score,
        factors=factors,
        tags=list(dict.fromkeys(tags)),
    )


def apply_ftid_gate_features(
    features: dict[str, Any],
    payload: dict[str, Any] | None,
    metadata: dict[str, Any] | None,
) -> dict[str, Any] | None:
    result = compute_ftid_gate(payload=payload, metadata=metadata)
    if result is None:
        return None
    features["ftid_score"] = round(result.score_0_100, 2)
    features["ftid_refund_hold"] = result.refund_hold
    features["ftid_intake_mismatch"] = result.refund_hold
    features["ftid_high"] = result.score_0_100 >= 40.0 or result.refund_hold
    if result.mismatch_class:
        features["ftid_mismatch_class"] = result.mismatch_class
        features[f"ftid_mismatch:{result.mismatch_class}"] = True
    features["ftid_state"] = result.state
    for f in result.factors:
        features[f"ftid_factor:{f.code}"] = True
    return result.evidence()
