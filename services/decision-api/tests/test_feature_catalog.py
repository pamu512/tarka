"""FeatureCatalog v1 evaluate-time checks."""

from decision_api.feature_catalog import apply_feature_catalog_v1


def test_payment_missing_amount_and_fingerprint_tags():
    tags: list[str] = []
    missing = apply_feature_catalog_v1(
        {},
        "payment",
        tags,
        fail_closed_event_types=frozenset({"payment"}),
    )
    assert "amount" in missing
    assert "device_fingerprint" in missing
    assert "feature:missing_amount" in tags
    assert "feature:missing_device_fingerprint" in tags
    assert "feature:catalog_fail_closed" in tags


def test_login_missing_fingerprint_degrade_only_without_fail_closed():
    tags: list[str] = []
    missing = apply_feature_catalog_v1(
        {},
        "login",
        tags,
        fail_closed_event_types=frozenset(),
    )
    assert missing == ["device_fingerprint"]
    assert "feature:catalog_fail_closed" not in tags


def test_payment_ok_when_present():
    tags: list[str] = []
    missing = apply_feature_catalog_v1(
        {"amount": 12.5, "device_fingerprint": "dev-1"},
        "payment",
        tags,
        fail_closed_event_types=frozenset({"payment"}),
    )
    assert missing == []
    assert tags == []
