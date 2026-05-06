from __future__ import annotations

import logging
import os
from collections.abc import Callable
from typing import Any

import numpy as np

"""Optional TreeSHAP explanations for a persisted LightGBM sklearn model (stretch / v1.2).

Enable with ``ML_SHAP_ENABLED=1`` and ``ML_LGBM_MODEL_PATH`` pointing to a ``joblib``-pickled
``lightgbm.LGBMClassifier`` or ``LGBMRegressor`` trained on the same feature order as
``heuristic.extract_feature_vector`` (9 features).

Install: ``pip install -e ".[shap]"`` in ``services/ml-scoring``.
"""
log = logging.getLogger(__name__)

_FEATURE_NAMES = [
    "amount",
    "hour_of_day",
    "is_new_device",
    "is_vpn",
    "is_emulator",
    "is_bot",
    "transaction_count_24h",
    "distinct_countries_7d",
    "account_age_days",
]

_model_cache: Any = None
_explainer_cache: Any = None


def _shap_enabled() -> bool:
    return os.environ.get("ML_SHAP_ENABLED", "").lower() in ("1", "true", "yes")


def _model_path() -> str:
    return (os.environ.get("ML_LGBM_MODEL_PATH") or "").strip()


def _load_model_and_explainer():
    global _model_cache, _explainer_cache
    if _model_cache is not None and _explainer_cache is not None:
        return _model_cache, _explainer_cache
    path = _model_path()
    if not path:
        return None, None
    try:
        import joblib
        import shap
    except ImportError:
        log.warning("ML_SHAP_ENABLED set but shap/joblib not installed; pip install -e '.[shap]'")
        return None, None
    try:
        model = joblib.load(path)
    except Exception as exc:
        log.warning("Failed to load LightGBM model from %s: %s", path, exc)
        return None, None
    try:
        explainer = shap.TreeExplainer(model)
    except Exception as exc:
        log.warning("TreeExplainer failed for %s: %s", path, exc)
        return None, None
    _model_cache = model
    _explainer_cache = explainer
    return model, explainer


def lgbm_score_and_shap_factors(
    features: dict[str, Any],
    extract_vector: Callable[[dict[str, Any]], list[float]],
) -> tuple[float | None, list[dict[str, Any]] | None]:
    """Return (score 0–100, top SHAP factors) or (None, None) if disabled or on error."""
    if not _shap_enabled() or not _model_path():
        return None, None
    model, explainer = _load_model_and_explainer()
    if model is None or explainer is None:
        return None, None
    vec = np.asarray([extract_vector(features)], dtype=np.float64)
    try:
        if hasattr(model, "predict_proba"):
            proba = model.predict_proba(vec)
            if proba.ndim == 2 and proba.shape[1] >= 2:
                score = float(max(0.0, min(100.0, proba[0, 1] * 100.0)))
            else:
                score = float(max(0.0, min(100.0, proba[0, 0] * 100.0)))
        else:
            raw = model.predict(vec)
            r0 = float(raw[0])
            score = float(max(0.0, min(100.0, r0 if r0 > 1.0 else r0 * 100.0)))

        shap_out = explainer.shap_values(vec)
        if isinstance(shap_out, list):
            shap_row = np.asarray(shap_out[1 if len(shap_out) > 1 else 0])[0]
        else:
            shap_row = np.asarray(shap_out)[0]
        if shap_row.ndim > 1:
            shap_row = shap_row.flatten()

        n = min(len(shap_row), len(_FEATURE_NAMES))
        pairs = [(abs(float(shap_row[i])), float(shap_row[i]), _FEATURE_NAMES[i]) for i in range(n)]
        pairs.sort(key=lambda x: -x[0])
        factors: list[dict[str, Any]] = []
        for _, val, name in pairs[:3]:
            factors.append(
                {
                    "code": f"SHAP_{name.upper()}",
                    "description": f"TreeSHAP contribution {val:+.4f} on `{name}` (v1.2 stretch)",
                    "impact": "high" if abs(val) > 0.15 else "medium",
                }
            )
        return score, factors
    except Exception as exc:
        log.warning("lgbm_score_and_shap_factors failed: %s", exc)
        return None, None


def reset_shap_cache() -> None:
    global _model_cache, _explainer_cache
    _model_cache = None
    _explainer_cache = None
