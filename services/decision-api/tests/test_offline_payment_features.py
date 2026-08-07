"""Offline payment feature wiring (Marketplace B1)."""

from decision_api.offline_payment_features import apply_offline_payment_features


def test_is_cod_from_payload_payment_method():
    features: dict = {}
    apply_offline_payment_features(
        features,
        {"payment_method": "COD", "amount": 100},
        None,
    )
    assert features["payment_method"] == "cod"
    assert features["is_cod"] is True
    assert features["is_offline_payment"] is True


def test_is_offline_payment_store_pickup():
    features: dict = {}
    apply_offline_payment_features(
        features,
        {"payment_method": "store_pickup"},
        None,
    )
    assert features["is_cod"] is False
    assert features["is_offline_payment"] is True


def test_metadata_bool_overrides_payment_method():
    features: dict = {}
    apply_offline_payment_features(
        features,
        {"payment_method": "card"},
        {"is_cod": True, "is_offline_payment": True},
    )
    assert features["payment_method"] == "card"
    assert features["is_cod"] is True
    assert features["is_offline_payment"] is True


def test_payment_method_from_metadata():
    features: dict = {}
    apply_offline_payment_features(
        features,
        {},
        {"payment_method": "cash_on_delivery"},
    )
    assert features["is_cod"] is True
