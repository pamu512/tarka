from __future__ import annotations

import json
import time
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
from sklearn.ensemble import GradientBoostingClassifier, IsolationForest
from sklearn.metrics import (
    auc,
    precision_recall_curve,
    roc_auc_score,
)
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import FunctionTransformer

"""Train anomaly detection and supervised fraud models, export to ONNX.

Usage:
    python train_anomaly_model.py

Outputs:
    ../models/anomaly-iforest/1/model.onnx  + metadata.json
    ../models/fraud-gbm/1/model.onnx        + metadata.json
"""

FEATURES = [
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

N_SAMPLES = 10_000
FRAUD_RATIO = 0.05
RANDOM_SEED = 42
MODELS_DIR = Path(__file__).resolve().parent.parent / "models"


# ---------------------------------------------------------------------------
# Synthetic data generation
# ---------------------------------------------------------------------------


def _generate_data(n: int = N_SAMPLES, seed: int = RANDOM_SEED) -> tuple[np.ndarray, np.ndarray]:
    """Return (X, y) where X has shape (n, 9) and y is 0/1."""
    rng = np.random.RandomState(seed)
    n_fraud = int(n * FRAUD_RATIO)
    n_legit = n - n_fraud

    def _legit_block(size: int) -> np.ndarray:
        amount = rng.lognormal(mean=4.0, sigma=1.0, size=size).clip(1, 50_000)
        hour = rng.normal(loc=14, scale=4, size=size).clip(0, 23).astype(int)
        is_new_device = (rng.random(size) < 0.08).astype(float)
        is_vpn = (rng.random(size) < 0.05).astype(float)
        is_emulator = (rng.random(size) < 0.01).astype(float)
        is_bot = (rng.random(size) < 0.005).astype(float)
        tx_count_24h = rng.poisson(lam=3, size=size).clip(0, 100).astype(float)
        countries_7d = rng.choice([1, 1, 1, 1, 2], size=size).astype(float)
        account_age = rng.exponential(scale=400, size=size).clip(1, 3650)
        return np.column_stack(
            [
                amount,
                hour,
                is_new_device,
                is_vpn,
                is_emulator,
                is_bot,
                tx_count_24h,
                countries_7d,
                account_age,
            ]
        )

    def _fraud_block(size: int) -> np.ndarray:
        amount = rng.lognormal(mean=7.5, sigma=1.2, size=size).clip(500, 100_000)
        hour = rng.choice([0, 1, 2, 3, 4, 23, 22], size=size).astype(float)
        is_new_device = (rng.random(size) < 0.65).astype(float)
        is_vpn = (rng.random(size) < 0.55).astype(float)
        is_emulator = (rng.random(size) < 0.30).astype(float)
        is_bot = (rng.random(size) < 0.20).astype(float)
        tx_count_24h = rng.poisson(lam=15, size=size).clip(0, 100).astype(float)
        countries_7d = rng.choice([2, 3, 4, 5, 6], size=size).astype(float)
        account_age = rng.exponential(scale=30, size=size).clip(0, 365)
        return np.column_stack(
            [
                amount,
                hour,
                is_new_device,
                is_vpn,
                is_emulator,
                is_bot,
                tx_count_24h,
                countries_7d,
                account_age,
            ]
        )

    X = np.vstack([_legit_block(n_legit), _fraud_block(n_fraud)]).astype(np.float32)
    y = np.concatenate([np.zeros(n_legit), np.ones(n_fraud)]).astype(np.int64)

    shuffle_idx = rng.permutation(n)
    return X[shuffle_idx], y[shuffle_idx]


# ---------------------------------------------------------------------------
# Normalisation (matches what the scoring service applies)
# ---------------------------------------------------------------------------

_NORM_DIVISORS = np.array([10_000, 24, 1, 1, 1, 1, 100, 10, 365], dtype=np.float32)


def normalize(X: np.ndarray) -> np.ndarray:
    return (X / _NORM_DIVISORS).astype(np.float32)


# ---------------------------------------------------------------------------
# Metrics helpers
# ---------------------------------------------------------------------------


def _print_metrics(name: str, y_true: np.ndarray, scores: np.ndarray) -> dict:
    """Print and return metrics dict for a given score array (higher = more fraud)."""
    auc_roc = roc_auc_score(y_true, scores)
    prec, rec, thresholds = precision_recall_curve(y_true, scores)
    pr_auc = auc(rec, prec)

    print(f"\n{'=' * 50}")
    print(f"  {name}")
    print(f"{'=' * 50}")
    print(f"  AUC-ROC:  {auc_roc:.4f}")
    print(f"  PR-AUC:   {pr_auc:.4f}")

    metrics = {"auc_roc": round(auc_roc, 4)}
    for t in [30, 50, 70, 80]:
        mask = scores >= (t / 100.0)
        tp = ((mask) & (y_true == 1)).sum()
        fp = ((mask) & (y_true == 0)).sum()
        fn = ((~mask) & (y_true == 1)).sum()
        p = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        r = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        f1 = 2 * p * r / (p + r) if (p + r) > 0 else 0.0
        print(f"  @threshold={t:3d}:  prec={p:.3f}  recall={r:.3f}  f1={f1:.3f}")
        metrics[f"precision_at_{t}"] = round(p, 4)
        metrics[f"recall_at_{t}"] = round(r, 4)
        metrics[f"f1_at_{t}"] = round(f1, 4)
    return metrics


# ---------------------------------------------------------------------------
# ONNX export
# ---------------------------------------------------------------------------


def _export_onnx(pipeline: Pipeline, name: str, n_features: int, output_dir: Path) -> Path:
    from skl2onnx import convert_sklearn
    from skl2onnx.common.data_types import FloatTensorType

    initial_type = [("X", FloatTensorType([None, n_features]))]
    onnx_model = convert_sklearn(pipeline, initial_types=initial_type, target_opset=15)
    onnx_path = output_dir / "model.onnx"
    with open(onnx_path, "wb") as f:
        f.write(onnx_model.SerializeToString())
    print(f"  Exported ONNX: {onnx_path}")
    return onnx_path


def _verify_onnx(onnx_path: Path, X_sample: np.ndarray) -> None:
    import onnxruntime as ort

    sess = ort.InferenceSession(str(onnx_path), providers=["CPUExecutionProvider"])
    input_name = sess.get_inputs()[0].name
    result = sess.run(None, {input_name: X_sample[:5]})
    print(f"  ONNX verification — sample output shape: {result[0].shape}")


# ---------------------------------------------------------------------------
# Model 1: Isolation Forest anomaly detector
# ---------------------------------------------------------------------------


def train_isolation_forest(X_norm: np.ndarray, y: np.ndarray) -> dict:
    print("\n>>> Training Isolation Forest (unsupervised) ...")
    t0 = time.time()

    iforest = IsolationForest(
        n_estimators=200,
        contamination=FRAUD_RATIO,
        random_state=RANDOM_SEED,
        n_jobs=-1,
    )

    def _score_transform(X: np.ndarray) -> np.ndarray:
        raw = iforest.decision_function(X)
        scaled = 1.0 - (raw - raw.min()) / (raw.max() - raw.min() + 1e-9)
        return scaled.reshape(-1, 1).astype(np.float32)

    iforest.fit(X_norm)
    elapsed = time.time() - t0
    print(f"  Fit in {elapsed:.1f}s")

    raw_scores = iforest.decision_function(X_norm)
    anomaly_scores = 1.0 - (raw_scores - raw_scores.min()) / (
        raw_scores.max() - raw_scores.min() + 1e-9
    )

    metrics = _print_metrics("Isolation Forest", y, anomaly_scores)

    pipe = Pipeline(
        [
            ("normalize", FunctionTransformer(normalize, validate=False)),
            ("iforest", iforest),
        ]
    )

    output_dir = MODELS_DIR / "anomaly-iforest" / "1"
    output_dir.mkdir(parents=True, exist_ok=True)

    onnx_path = _export_onnx(pipe, "anomaly-iforest", len(FEATURES), output_dir)
    _verify_onnx(onnx_path, X_norm[:5].copy())

    meta = {
        "name": "anomaly-iforest",
        "version": 1,
        "description": "Isolation Forest anomaly detector for transaction fraud",
        "algorithm": "IsolationForest",
        "framework": "scikit-learn + skl2onnx",
        "input_schema": {
            "features": FEATURES,
            "normalization": "built-in",
        },
        "output_schema": {
            "type": "anomaly_score",
            "range": [0, 100],
            "threshold_deny": 80,
            "threshold_review": 50,
        },
        "training_metrics": {
            k: round(v, 4) if isinstance(v, float) else v for k, v in metrics.items()
        },
        "training_data": {
            "samples": N_SAMPLES,
            "fraud_ratio": FRAUD_RATIO,
            "generated": True,
        },
        "traffic_weight": 50,
        "active": True,
        "created_at": datetime.now(UTC).isoformat(),
    }
    meta_path = output_dir / "metadata.json"
    meta_path.write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    print(f"  Saved metadata: {meta_path}")

    return metrics


# ---------------------------------------------------------------------------
# Model 2: Gradient Boosted classifier (supervised)
# ---------------------------------------------------------------------------


def train_gbm(X_norm: np.ndarray, y: np.ndarray) -> dict:
    print("\n>>> Training Gradient Boosted Classifier (supervised) ...")
    t0 = time.time()

    X_train, X_test, y_train, y_test = train_test_split(
        X_norm,
        y,
        test_size=0.2,
        stratify=y,
        random_state=RANDOM_SEED,
    )

    gbm = GradientBoostingClassifier(
        n_estimators=200,
        max_depth=5,
        learning_rate=0.1,
        subsample=0.8,
        random_state=RANDOM_SEED,
    )
    gbm.fit(X_train, y_train)
    elapsed = time.time() - t0
    print(f"  Fit in {elapsed:.1f}s")

    proba_test = gbm.predict_proba(X_test)[:, 1]
    metrics = _print_metrics("Gradient Boosted Classifier (test set)", y_test, proba_test)

    proba_all = gbm.predict_proba(X_norm)[:, 1]
    _print_metrics("Gradient Boosted Classifier (full set)", y, proba_all)

    pipe = Pipeline(
        [
            ("normalize", FunctionTransformer(normalize, validate=False)),
            ("gbm", gbm),
        ]
    )

    output_dir = MODELS_DIR / "fraud-gbm" / "1"
    output_dir.mkdir(parents=True, exist_ok=True)

    onnx_path = _export_onnx(pipe, "fraud-gbm", len(FEATURES), output_dir)
    _verify_onnx(onnx_path, X_norm[:5].copy())

    meta = {
        "name": "fraud-gbm",
        "version": 1,
        "description": "Gradient Boosted classifier for supervised fraud detection",
        "algorithm": "GradientBoostingClassifier",
        "framework": "scikit-learn + skl2onnx",
        "input_schema": {
            "features": FEATURES,
            "normalization": "built-in",
        },
        "output_schema": {
            "type": "fraud_probability",
            "range": [0, 100],
        },
        "training_metrics": {
            k: round(v, 4) if isinstance(v, float) else v for k, v in metrics.items()
        },
        "training_data": {
            "samples": N_SAMPLES,
            "fraud_ratio": FRAUD_RATIO,
            "generated": True,
        },
        "traffic_weight": 50,
        "active": True,
        "created_at": datetime.now(UTC).isoformat(),
    }
    meta_path = output_dir / "metadata.json"
    meta_path.write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    print(f"  Saved metadata: {meta_path}")

    return metrics


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    print("Generating synthetic transaction data ...")
    X_raw, y = _generate_data()
    print(f"  {X_raw.shape[0]} samples, {y.sum():.0f} fraud ({y.mean() * 100:.1f}%)")
    print(f"  Features: {FEATURES}")

    X_norm = normalize(X_raw)

    iforest_metrics = train_isolation_forest(X_norm, y)
    gbm_metrics = train_gbm(X_norm, y)

    print("\n" + "=" * 50)
    print("  DONE — Models saved under:", MODELS_DIR)
    print("=" * 50)
    print(f"  anomaly-iforest  AUC={iforest_metrics['auc_roc']:.4f}")
    print(f"  fraud-gbm        AUC={gbm_metrics['auc_roc']:.4f}")


if __name__ == "__main__":
    main()
