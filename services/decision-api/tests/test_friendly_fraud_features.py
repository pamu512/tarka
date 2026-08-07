"""Friendly-fraud feature wiring (metadata-first evaluate path)."""

from decision_api.friendly_fraud_features import apply_friendly_fraud_features


def test_delivery_hash_mismatch():
    features: dict = {}
    apply_friendly_fraud_features(
        features,
        {
            "delivery_confirmation_hash": "abc123",
            "expected_delivery_hash": "def456",
        },
        None,
    )
    assert features["delivery_hash_mismatch"] is True
    assert features["is_friendly_fraud_risk"] is True


def test_delivery_hash_match_no_mismatch():
    features: dict = {}
    apply_friendly_fraud_features(
        features,
        {
            "pod_hash": "samehash",
            "expected_delivery_hash": "samehash",
        },
        None,
    )
    assert features["delivery_hash_mismatch"] is False
    assert features["is_friendly_fraud_risk"] is False


def test_prior_orders_and_dispute_window_composite():
    features: dict = {}
    apply_friendly_fraud_features(
        features,
        {
            "prior_successful_orders_same_ip": 3,
            "dispute_hours_since_delivery": 48,
        },
        None,
    )
    assert features["prior_successful_orders_same_ip"] == 3
    assert features["dispute_within_delivery_window"] is True
    assert features["is_friendly_fraud_risk"] is True


def test_prior_orders_below_threshold_no_risk():
    features: dict = {}
    apply_friendly_fraud_features(
        features,
        {
            "prior_successful_orders_same_ip": 1,
            "dispute_hours_since_delivery": 24,
        },
        None,
    )
    assert features["is_friendly_fraud_risk"] is False


def test_dispute_outside_window_no_composite_risk():
    features: dict = {}
    apply_friendly_fraud_features(
        features,
        {
            "prior_successful_orders_same_ip": 5,
            "dispute_hours_since_delivery": 96,
        },
        None,
    )
    assert features["dispute_within_delivery_window"] is False
    assert features["is_friendly_fraud_risk"] is False


def test_fail_closed_on_bad_types():
    features: dict = {}
    apply_friendly_fraud_features(
        features,
        {
            "prior_successful_orders_same_ip": "not-a-number",
            "dispute_hours_since_delivery": True,
            "delivery_confirmation_hash": 12345,
            "expected_delivery_hash": "abc",
        },
        None,
    )
    assert "prior_successful_orders_same_ip" not in features
    assert "dispute_within_delivery_window" not in features
    assert "delivery_hash_mismatch" not in features
    assert "is_friendly_fraud_risk" not in features


def test_prior_orders_from_payload():
    features: dict = {}
    apply_friendly_fraud_features(
        features,
        {"dispute_hours_since_delivery": 12},
        {"prior_successful_orders_same_ip": 4},
    )
    assert features["prior_successful_orders_same_ip"] == 4
    assert features["is_friendly_fraud_risk"] is True
