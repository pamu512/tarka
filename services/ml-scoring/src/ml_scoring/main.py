import os
import sys
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Request
from pydantic import BaseModel, Field

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", "shared"))
from observability import setup_observability  # noqa: E402

from ml_scoring.adaptive import get_detector, init_detector, reset_detector, save_detector  # noqa: E402
from ml_scoring.explainability import (  # noqa: E402
    explain_score,
    ml_summary_from_factors,
    top_factors_from_explanations,
)
from ml_scoring.heuristic import extract_feature_vector as _extract_feature_vector  # noqa: E402
from ml_scoring.heuristic import heuristic_score as _heuristic_score  # noqa: E402
from ml_scoring.model_registry import ModelRegistry  # noqa: E402
from ml_scoring.shap_explainer import lgbm_score_and_shap_factors  # noqa: E402

DISABLE_ML = os.environ.get("DISABLE_ML", "").lower() in ("1", "true", "yes")
MODEL_VERSION = os.environ.get("ML_MODEL_VERSION", "heuristic-v1")
ONNX_PATH = os.environ.get("ONNX_MODEL_PATH", "")
MODELS_DIR = os.environ.get(
    "MODELS_DIR",
    str(Path(__file__).resolve().parent.parent.parent / "models"),
)

registry = ModelRegistry(MODELS_DIR)

_onnx_session = None
_onnx_input_name: str = ""

# ---------- auth ----------

_valid_api_keys: frozenset[str] | None = None


def _get_api_keys() -> frozenset[str]:
    global _valid_api_keys
    if _valid_api_keys is None:
        raw = os.environ.get("API_KEYS", "").strip()
        _valid_api_keys = frozenset(k.strip() for k in raw.split(",") if k.strip()) if raw else frozenset()
    return _valid_api_keys


async def require_api_key(request: Request) -> None:
    keys = _get_api_keys()
    if not keys:
        return
    if request.headers.get("x-api-key", "") not in keys:
        raise HTTPException(status_code=401, detail="invalid or missing API key")


ADAPTIVE_WEIGHT = float(os.environ.get("ADAPTIVE_WEIGHT", "0.3"))
_score_counter: int = 0


@asynccontextmanager
async def lifespan(_: FastAPI):
    global _onnx_session, _onnx_input_name

    registry.scan()
    init_detector()

    if ONNX_PATH and not DISABLE_ML:
        try:
            import onnxruntime as ort

            _onnx_session = ort.InferenceSession(ONNX_PATH, providers=["CPUExecutionProvider"])
            _onnx_input_name = _onnx_session.get_inputs()[0].name
        except Exception:
            _onnx_session = None
    yield
    save_detector()
    _onnx_session = None


app = FastAPI(
    title="Tarka ML Scoring",
    version="3.0.0",
    lifespan=lifespan,
    dependencies=[Depends(require_api_key)],
)
setup_observability(app, "ml-scoring")


class ScoreRequest(BaseModel):
    tenant_id: str
    entity_id: str
    event_type: str | None = None
    features: dict[str, Any] = Field(default_factory=dict)


def _extract_onnx_score(outputs: list) -> float:
    """Extract a continuous score from ONNX model outputs.

    skl2onnx classifiers output [labels, probabilities].
    IsolationForest outputs [labels, decision_function_scores].
    We always use output[1] for continuous scores.
    For classifiers, take probability of positive class (column 1).
    For anomaly detectors, scale decision_function to [0, 100].
    """
    if len(outputs) < 2:
        return float(outputs[0].flatten()[0] * 100)
    scores = outputs[1]
    if scores.ndim >= 2 and scores.shape[1] >= 2:
        return float(scores[0, 1] * 100)
    raw = float(scores.flatten()[0])
    if raw < 0:
        return max(0.0, min(100.0, 50.0 - raw * 100))
    return max(0.0, min(100.0, raw * 100))


def _onnx_score(features: dict[str, Any]) -> float | None:
    if not _onnx_session:
        return None
    try:
        import numpy as np

        vec = np.array([_extract_feature_vector(features)], dtype=np.float32)
        outputs = _onnx_session.run(None, {_onnx_input_name: vec})
        return _extract_onnx_score(outputs)
    except Exception:
        return None


def _score_with_model_version(mv, features: dict[str, Any]) -> tuple[float | None, str]:
    """Try ONNX session from a registry ModelVersion, fall back to heuristic."""
    if mv and mv.onnx_session:
        try:
            import numpy as np

            vec = np.array([_extract_feature_vector(features)], dtype=np.float32)
            outputs = mv.onnx_session.run(None, {mv.onnx_input_name: vec})
            return _extract_onnx_score(outputs), f"{mv.name}/v{mv.version}+onnx"
        except Exception:
            pass
    return None, ""


@app.get("/v1/health")
async def health():
    shap_on = os.environ.get("ML_SHAP_ENABLED", "").lower() in ("1", "true", "yes")
    lgbm_path = bool((os.environ.get("ML_LGBM_MODEL_PATH") or "").strip())
    return {
        "status": "ok",
        "disable_ml": DISABLE_ML,
        "model_version": MODEL_VERSION,
        "onnx_loaded": _onnx_session is not None,
        "registry_models": len(registry.list_models()),
        "shap_stretch_enabled": shap_on and lgbm_path,
    }


def _extract_numeric_features(features: dict[str, Any]) -> dict[str, float]:
    """Pull all numeric values from raw features for the adaptive detector."""
    out: dict[str, float] = {}
    for k, v in features.items():
        if isinstance(v, bool):
            out[k] = 1.0 if v else 0.0
        elif isinstance(v, (int, float)):
            out[k] = float(v)
    return out


def _background_adaptive_update(numeric_features: dict[str, float]) -> None:
    global _score_counter
    detector = get_detector()
    detector.partial_fit(numeric_features)
    _score_counter += 1
    if _score_counter % 100 == 0:
        save_detector()


@app.post("/v1/score")
async def score(body: ScoreRequest, bg: BackgroundTasks):
    if DISABLE_ML:
        return {
            "score": 0.0,
            "model_version": "disabled",
            "ml_top_factors": [],
            "ml_summary": None,
        }

    mv, model_name, version = registry.get_model(body.tenant_id)

    numeric_features = _extract_numeric_features(body.features)
    detector = get_detector()
    adaptive_score, contributions = detector.score(numeric_features)

    base_score: float
    model_label: str

    if mv:
        t0 = time.perf_counter()
        onnx_s, label = _score_with_model_version(mv, body.features)
        if onnx_s is not None:
            elapsed = (time.perf_counter() - t0) * 1000
            registry.record_inference(model_name, version, elapsed)
            base_score = max(0.0, min(100.0, onnx_s))
            model_label = label
        else:
            t0 = time.perf_counter()
            base_score = _heuristic_score(body.features)
            elapsed = (time.perf_counter() - t0) * 1000
            registry.record_inference(model_name, version, elapsed)
            model_label = f"{model_name}/v{version}"
    else:
        onnx_s = _onnx_score(body.features)
        if onnx_s is not None:
            base_score = max(0.0, min(100.0, onnx_s))
            model_label = MODEL_VERSION + "+onnx"
        else:
            base_score = _heuristic_score(body.features)
            model_label = MODEL_VERSION

    shap_s, shap_factors = lgbm_score_and_shap_factors(body.features, _extract_feature_vector)
    if shap_s is not None and shap_factors:
        base_score = shap_s
        model_label = f"{model_label}+lgbm-shap" if model_label else "lgbm-shap"

    blended = round((1 - ADAPTIVE_WEIGHT) * base_score + ADAPTIVE_WEIGHT * adaptive_score, 2)
    blended = max(0.0, min(100.0, blended))

    mt = (
        "lgbm"
        if "lgbm-shap" in model_label
        else ("onnx" if "onnx" in model_label else "heuristic")
    )
    explanations = explain_score(
        blended,
        body.features,
        model_type=mt,
        adaptive_contributions=contributions if contributions and contributions[0].get("feature") != "insufficient_data" else None,
    )

    if shap_factors:
        ml_top_factors = shap_factors
    else:
        ml_top_factors = top_factors_from_explanations(explanations, limit=3)
    ml_summary = ml_summary_from_factors(blended, ml_top_factors, model_label)

    bg.add_task(_background_adaptive_update, numeric_features)

    return {
        "score": blended,
        "model": model_label,
        "version": "v1",
        "adaptive_score": adaptive_score,
        "explanations": explanations,
        "feature_contributions": contributions,
        "ml_top_factors": ml_top_factors,
        "ml_summary": ml_summary,
    }


# ---------- adaptive endpoints ----------


@app.get("/v1/adaptive/stats")
async def adaptive_stats():
    return get_detector().get_stats()


@app.get("/v1/adaptive/drift")
async def adaptive_drift():
    """Get drift detection status and history."""
    detector = get_detector()
    return {
        "drift": detector._drift.get_stats(),
        "current_learning_rate": detector.lr,
        "base_learning_rate": detector._base_lr,
        "boost_remaining": detector._boost_remaining,
    }


@app.get("/v1/adaptive/thresholds")
async def adaptive_thresholds():
    """Get auto-calibrated scoring thresholds."""
    return get_detector().calibrate_thresholds()


@app.post("/v1/adaptive/reset")
async def adaptive_reset():
    """Reset the adaptive model (start fresh)."""
    reset_detector()
    return {"ok": True, "message": "Adaptive model reset to initial state"}


# ---------- registry endpoints ----------


@app.get("/v1/models")
async def list_models():
    return {"models": registry.list_models()}


class ActivateRequest(BaseModel):
    version: int


@app.post("/v1/models/{name}/activate")
async def activate_model(name: str, body: ActivateRequest):
    if not registry.is_approved(name, body.version):
        raise HTTPException(409, f"model '{name}' version {body.version} is not approved")
    ok = registry.activate_version(name, body.version)
    if not ok:
        raise HTTPException(404, f"model '{name}' version {body.version} not found")
    return {"ok": True, "model": name, "active_version": body.version}


@app.get("/v1/models/{name}/stats")
async def model_stats(name: str):
    stats = registry.get_model_stats(name)
    if not stats:
        raise HTTPException(404, f"model '{name}' not found")
    return {"model": name, "versions": stats}


class ApproveRequest(BaseModel):
    version: int
    approved_by: str = Field(min_length=1, max_length=128)
    stage: str = Field(default="approved", min_length=1, max_length=64)


@app.post("/v1/models/{name}/approve")
async def approve_model(name: str, body: ApproveRequest):
    ok = registry.approve_version(name, body.version, body.approved_by, body.stage)
    if not ok:
        raise HTTPException(404, f"model '{name}' version {body.version} not found")
    return {
        "ok": True,
        "model": name,
        "version": body.version,
        "approved_by": body.approved_by,
        "stage": body.stage,
    }


class TrafficSplitRequest(BaseModel):
    weights: dict[int, int] = Field(default_factory=dict)


@app.post("/v1/models/{name}/traffic-split")
async def set_model_traffic_split(name: str, body: TrafficSplitRequest):
    ok = registry.set_traffic_split(name, body.weights)
    if not ok:
        raise HTTPException(400, "invalid model name, versions, or weights (must sum to 100)")
    return {"ok": True, "model": name, "weights": body.weights}


@app.post("/v1/models/{name}/rollback")
async def rollback_model(name: str):
    target = registry.rollback_to_previous(name)
    if target is None:
        raise HTTPException(409, f"no previous version available for model '{name}'")
    return {"ok": True, "model": name, "rolled_back_to": target}


@app.get("/v1/models/{name}/{version}/lineage")
async def model_lineage(name: str, version: int):
    lineage = registry.lineage_signature(name, version)
    if not lineage:
        raise HTTPException(404, f"model '{name}' version {version} not found")
    return {"ok": True, "model": name, "version": version, "lineage": lineage}
