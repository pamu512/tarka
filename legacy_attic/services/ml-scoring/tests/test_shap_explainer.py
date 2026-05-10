"""Optional TreeSHAP path — disabled by default (no heavy deps in CI)."""

import os

import pytest
from ml_scoring.shap_explainer import (
    lgbm_score_and_shap_factors,
    reset_shap_cache,
)


def _vec(f):
    from ml_scoring.heuristic import extract_feature_vector

    return extract_feature_vector(f)


@pytest.fixture(autouse=True)
def _clear_shap_env(monkeypatch):
    monkeypatch.delenv("ML_SHAP_ENABLED", raising=False)
    monkeypatch.delenv("ML_LGBM_MODEL_PATH", raising=False)
    reset_shap_cache()
    yield
    reset_shap_cache()


def test_shap_disabled_when_env_off():
    assert lgbm_score_and_shap_factors({"amount": 100.0}, _vec) == (None, None)


def test_shap_disabled_without_model_path(monkeypatch):
    monkeypatch.setenv("ML_SHAP_ENABLED", "1")
    assert lgbm_score_and_shap_factors({"amount": 100.0}, _vec) == (None, None)


@pytest.mark.skipif(
    not os.environ.get("ML_SCORING_TEST_SHAP"),
    reason="Set ML_SCORING_TEST_SHAP=1 and install .[shap] with a valid ML_LGBM_MODEL_PATH to run",
)
def test_shap_optional_integration(monkeypatch):
    """Opt-in: train a tiny LGBM on 9 features, joblib-save, set path + ML_SHAP_ENABLED."""
    monkeypatch.setenv("ML_SHAP_ENABLED", "1")
    path = os.environ.get("ML_LGBM_MODEL_PATH", "").strip()
    if not path:
        pytest.skip("ML_LGBM_MODEL_PATH not set")
    reset_shap_cache()
    features = {
        "amount": 5000.0,
        "hour_of_day": 14.0,
        "is_new_device": 1.0,
        "is_vpn": 0.0,
        "is_emulator": 0.0,
        "is_bot": 0.0,
        "transaction_count_24h": 5.0,
        "distinct_countries_7d": 1.0,
        "account_age_days": 365.0,
    }
    score, factors = lgbm_score_and_shap_factors(features, _vec)
    assert score is not None and 0 <= score <= 100
    assert factors and all("SHAP_" in f["code"] for f in factors)
