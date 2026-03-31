"""Unit tests for the feature-service — derived feature computation and snapshot."""
import math

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from feature_service.main import (
    _compute_amount_features,
    _compute_time_features,
    _build_vector,
    AMOUNT_BUCKETS,
    VECTOR_KEYS,
)


# ---------- _compute_amount_features ----------


class TestComputeAmountFeatures:
    def test_amount_log_computation(self):
        features = _compute_amount_features({"amount": 999})
        assert features["amount_log"] == round(math.log10(1000), 4)

    def test_zero_amount(self):
        features = _compute_amount_features({"amount": 0})
        assert features["amount_log"] == 0.0
        assert features["amount_bucket"] == "micro"

    def test_missing_amount(self):
        features = _compute_amount_features({})
        assert features["amount_log"] == 0.0
        assert features["amount_bucket"] == "micro"

    def test_micro_bucket(self):
        features = _compute_amount_features({"amount": 5})
        assert features["amount_bucket"] == "micro"

    def test_small_bucket(self):
        features = _compute_amount_features({"amount": 50})
        assert features["amount_bucket"] == "small"

    def test_medium_bucket(self):
        features = _compute_amount_features({"amount": 500})
        assert features["amount_bucket"] == "medium"

    def test_large_bucket(self):
        features = _compute_amount_features({"amount": 5000})
        assert features["amount_bucket"] == "large"

    def test_xlarge_bucket(self):
        features = _compute_amount_features({"amount": 50000})
        assert features["amount_bucket"] == "xlarge"

    def test_invalid_amount_coerced_to_zero(self):
        features = _compute_amount_features({"amount": "not-a-number"})
        assert features["amount_log"] == 0.0


# ---------- _compute_time_features ----------


class TestComputeTimeFeatures:
    def test_returns_required_keys(self):
        features = _compute_time_features()
        assert "hour_of_day" in features
        assert "day_of_week" in features
        assert "is_weekend" in features
        assert "is_night_hours" in features

    def test_hour_range(self):
        features = _compute_time_features()
        assert 0 <= features["hour_of_day"] <= 23

    def test_day_of_week_range(self):
        features = _compute_time_features()
        assert 0 <= features["day_of_week"] <= 6

    def test_is_weekend_is_bool(self):
        features = _compute_time_features()
        assert isinstance(features["is_weekend"], bool)

    def test_is_night_hours_is_bool(self):
        features = _compute_time_features()
        assert isinstance(features["is_night_hours"], bool)


# ---------- _build_vector ----------


class TestBuildVector:
    def test_vector_length_matches_keys(self):
        features = {"amount_log": 2.5, "hour_of_day": 14, "day_of_week": 2}
        vec = _build_vector(features)
        assert len(vec) == len(VECTOR_KEYS)

    def test_boolean_features_mapped_correctly(self):
        features = {"is_weekend": True, "is_night_hours": False}
        vec = _build_vector(features)
        weekend_idx = VECTOR_KEYS.index("is_weekend")
        night_idx = VECTOR_KEYS.index("is_night_hours")
        assert vec[weekend_idx] == 1.0
        assert vec[night_idx] == 0.0

    def test_amount_bucket_one_hot(self):
        features = {"amount_bucket": "medium"}
        vec = _build_vector(features)
        medium_idx = VECTOR_KEYS.index("amount_bucket_medium")
        micro_idx = VECTOR_KEYS.index("amount_bucket_micro")
        assert vec[medium_idx] == 1.0
        assert vec[micro_idx] == 0.0

    def test_missing_features_default_to_zero(self):
        vec = _build_vector({})
        assert all(v == 0.0 for v in vec)

    def test_numeric_values_pass_through(self):
        features = {"email_risk_score": 42.5}
        vec = _build_vector(features)
        idx = VECTOR_KEYS.index("email_risk_score")
        assert vec[idx] == 42.5


# ---------- Snapshot endpoint ----------


class TestSnapshotEndpoint:
    @pytest.fixture
    def client(self):
        with patch.dict("os.environ", {"API_KEYS": "", "ENRICHMENT_URL": "", "REDIS_TAGS_HTTP": ""}):
            from feature_service.main import app, _valid_api_keys
            import feature_service.main as mod
            mod._valid_api_keys = None
            from fastapi.testclient import TestClient
            with TestClient(app) as c:
                yield c

    def test_snapshot_basic(self, client):
        r = client.post("/v1/snapshot", json={
            "tenant_id": "t1",
            "entity_id": "e1",
            "event_type": "payment",
            "payload": {"amount": 250},
        })
        assert r.status_code == 200
        data = r.json()
        assert data["tenant_id"] == "t1"
        assert "features" in data
        assert "feature_vector" in data
        assert len(data["feature_vector"]) == len(VECTOR_KEYS)
        assert data["features"]["amount_bucket"] == "medium"

    def test_snapshot_includes_time_features(self, client):
        r = client.post("/v1/snapshot", json={
            "tenant_id": "t1",
            "entity_id": "e1",
            "event_type": "login",
            "payload": {},
        })
        assert r.status_code == 200
        features = r.json()["features"]
        assert "hour_of_day" in features
        assert "is_weekend" in features

    def test_snapshot_validation_error(self, client):
        r = client.post("/v1/snapshot", json={"tenant_id": "t1"})
        assert r.status_code == 422
