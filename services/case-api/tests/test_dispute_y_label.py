"""Unit: dispute outcome → calibration y_label mapping."""

from case_api.dispute_y_label import (
    dispute_outcome_to_training_label,
    dispute_outcome_to_y_label,
)


def test_dispute_outcome_to_y_label_fraud():
    assert dispute_outcome_to_y_label("fraud_confirmed") == "1"
    assert dispute_outcome_to_y_label("merchant_fault") == "1"
    assert dispute_outcome_to_y_label("FRAUD_CONFIRMED") == "1"


def test_dispute_outcome_to_y_label_legitimate():
    assert dispute_outcome_to_y_label("false_positive") == "0"
    assert dispute_outcome_to_y_label("customer_fault") == "0"


def test_dispute_outcome_to_y_label_skips_inconclusive():
    assert dispute_outcome_to_y_label("inconclusive") is None
    assert dispute_outcome_to_y_label("") is None
    assert dispute_outcome_to_y_label("unknown_outcome") is None


def test_dispute_outcome_to_training_label():
    assert dispute_outcome_to_training_label("fraud_confirmed") == ("fraud", "fraud_confirmed")
    assert dispute_outcome_to_training_label("false_positive") == ("not_fraud", "false_positive")
    assert dispute_outcome_to_training_label("inconclusive") == ("unknown", "inconclusive")
