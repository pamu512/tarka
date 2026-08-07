"""Map dispute terminal outcomes to training / calibration labels."""

from __future__ import annotations


def dispute_outcome_to_training_label(outcome: str) -> tuple[str, str]:
    """Return ``(case_management_label, dispute_outcome)``."""
    o = (outcome or "").strip().lower()
    if o in ("fraud_confirmed", "merchant_fault"):
        return "fraud", o
    if o in ("false_positive", "customer_fault"):
        return "not_fraud", o
    if o in ("inconclusive",):
        return "unknown", o
    return "unknown", o


def dispute_outcome_to_y_label(outcome: str) -> str | None:
    """Map terminal dispute outcome to calibration y_label (0/1). None if not mappable."""
    o = (outcome or "").strip().lower()
    if o in ("fraud_confirmed", "merchant_fault"):
        return "1"
    if o in ("false_positive", "customer_fault"):
        return "0"
    return None
