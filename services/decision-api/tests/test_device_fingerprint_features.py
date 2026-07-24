"""Contract: device_fingerprint in feature snapshot and evaluate feature merge."""

from decision_api.device_feature_merge import merge_device_context_into_features
from decision_api.schemas import DeviceContextIn


def test_merge_device_context_sets_device_fingerprint_from_device_id():
    features: dict = {"amount": 1}
    merge_device_context_into_features(
        features,
        DeviceContextIn(device_id="dev-abc", platform="web", signals={}),
    )
    assert features["device_fingerprint"] == "dev-abc"
    assert isinstance(features["device_fingerprint"], str)


def test_merge_device_context_signals_take_precedence_over_device_id():
    features: dict = {}
    merge_device_context_into_features(
        features,
        DeviceContextIn(
            device_id="dev-from-id",
            platform="web",
            signals={"device_fingerprint": "fp-from-signals"},
        ),
    )
    assert features["device_fingerprint"] == "fp-from-signals"


def test_merge_device_context_noop_when_absent():
    features = {"x": 1}
    merge_device_context_into_features(features, None)
    assert "device_fingerprint" not in features
