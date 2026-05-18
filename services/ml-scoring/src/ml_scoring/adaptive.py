"""Zero-retrain adaptive anomaly detection using a lightweight autoencoder.

Architecture: Input(N) → Dense(hidden) → ReLU → Dense(N) → sigmoid
The model reconstructs input features; reconstruction error = anomaly score.
Weights are updated online via mini-SGD after each observation.
No explicit retraining cycle needed — adapts continuously.
"""

import json
import logging
import math
import os
import threading
from datetime import datetime, timezone
from typing import Any

import numpy as np

log = logging.getLogger(__name__)


class AdaptiveAutoencoder:
    """Pure-numpy autoencoder for online anomaly detection.

    Features:
    - Learns to reconstruct normal behavior patterns
    - Reconstruction error = anomaly score
    - Online weight updates with configurable learning rate
    - Running statistics for feature normalization
    - Thread-safe for concurrent scoring/training
    """

    def __init__(
        self,
        input_dim: int = 32,
        hidden_dim: int = 16,
        learning_rate: float = 0.001,
        alpha: float | None = None,
        momentum: float = 0.9,
        decay: float = 0.999,
    ):
        self.input_dim = input_dim
        self.hidden_dim = hidden_dim
        self.lr = alpha if alpha is not None else learning_rate
        self.momentum = momentum
        self.decay = decay
        self._lock = threading.Lock()
        self._count = 0

        self._feature_names: list[str] = []
        self._feature_index: dict[str, int] = {}
        self._running_mean = np.zeros(input_dim, dtype=np.float64)
        self._running_var = np.ones(input_dim, dtype=np.float64)

        # Xavier initialization
        scale_enc = np.sqrt(2.0 / (input_dim + hidden_dim))
        scale_dec = np.sqrt(2.0 / (hidden_dim + input_dim))
        self.W_enc = np.random.randn(input_dim, hidden_dim).astype(np.float64) * scale_enc
        self.b_enc = np.zeros(hidden_dim, dtype=np.float64)
        self.W_dec = np.random.randn(hidden_dim, input_dim).astype(np.float64) * scale_dec
        self.b_dec = np.zeros(input_dim, dtype=np.float64)

        # Momentum buffers
        self._vW_enc = np.zeros_like(self.W_enc)
        self._vb_enc = np.zeros_like(self.b_enc)
        self._vW_dec = np.zeros_like(self.W_dec)
        self._vb_dec = np.zeros_like(self.b_dec)

        # Error tracking
        self._recent_errors: list[float] = []
        self._error_ema = 0.0
        self._error_ema_var = 1.0

        # Drift detection
        self._drift = DriftDetector()
        self._base_lr = self.lr
        self._boost_remaining = 0

    # ------------------------------------------------------------------
    # Activation helpers
    # ------------------------------------------------------------------

    def _relu(self, x: np.ndarray) -> np.ndarray:
        return np.maximum(0, x)

    def _relu_deriv(self, x: np.ndarray) -> np.ndarray:
        return (x > 0).astype(np.float64)

    def _sigmoid(self, x: np.ndarray) -> np.ndarray:
        return 1.0 / (1.0 + np.exp(-np.clip(x, -500, 500)))

    # ------------------------------------------------------------------
    # Normalization
    # ------------------------------------------------------------------

    def _normalize(self, raw: np.ndarray) -> np.ndarray:
        std = np.sqrt(self._running_var + 1e-8)
        return (raw - self._running_mean) / std

    def _update_running_stats(self, raw: np.ndarray, alpha: float = 0.01) -> None:
        self._running_mean = (1 - alpha) * self._running_mean + alpha * raw
        self._running_var = (1 - alpha) * self._running_var + alpha * (
            raw - self._running_mean
        ) ** 2

    # ------------------------------------------------------------------
    # Feature mapping
    # ------------------------------------------------------------------

    def _features_to_vector(self, features: dict[str, float]) -> np.ndarray:
        vec = np.zeros(self.input_dim, dtype=np.float64)
        for name, value in features.items():
            fval = float(value)
            if not np.isfinite(fval):
                continue
            if name not in self._feature_index:
                if len(self._feature_index) < self.input_dim:
                    idx = len(self._feature_index)
                    self._feature_index[name] = idx
                    self._feature_names.append(name)
                else:
                    continue
            idx = self._feature_index[name]
            vec[idx] = fval
        return vec

    # ------------------------------------------------------------------
    # Forward / backward
    # ------------------------------------------------------------------

    def _forward(self, x: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Forward pass.  Returns (hidden_pre_act, hidden, output)."""
        h_pre = x @ self.W_enc + self.b_enc
        h = self._relu(h_pre)
        out = self._sigmoid(h @ self.W_dec + self.b_dec)
        return h_pre, h, out

    def _backward_and_update(
        self,
        x: np.ndarray,
        h_pre: np.ndarray,
        h: np.ndarray,
        out: np.ndarray,
    ) -> None:
        """Backprop + SGD with momentum for a single sample."""
        d_out = (out - x) * out * (1 - out)  # MSE gradient * sigmoid derivative

        dW_dec = np.outer(h, d_out)
        db_dec = d_out

        d_h = d_out @ self.W_dec.T * self._relu_deriv(h_pre)
        dW_enc = np.outer(x, d_h)
        db_enc = d_h

        for g in [dW_enc, db_enc, dW_dec, db_dec]:
            np.clip(g, -1.0, 1.0, out=g)

        lr = self.lr * (self.decay ** (self._count / 1000))

        self._vW_enc = self.momentum * self._vW_enc - lr * dW_enc
        self._vb_enc = self.momentum * self._vb_enc - lr * db_enc
        self._vW_dec = self.momentum * self._vW_dec - lr * dW_dec
        self._vb_dec = self.momentum * self._vb_dec - lr * db_dec

        self.W_enc += self._vW_enc
        self.b_enc += self._vb_enc
        self.W_dec += self._vW_dec
        self.b_dec += self._vb_dec

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def partial_fit(self, features: dict[str, float], label: int | None = None) -> None:
        """Online weight update with a single observation."""
        with self._lock:
            raw = self._features_to_vector(features)
            self._update_running_stats(raw)
            x = self._normalize(raw)
            x_clipped = np.clip(x, -5, 5)
            x_scaled = self._sigmoid(x_clipped)

            h_pre, h, out = self._forward(x_scaled)
            self._backward_and_update(x_scaled, h_pre, h, out)
            self._count += 1

            error = float(np.mean((out - x_scaled) ** 2))
            self._recent_errors.append(error)
            if len(self._recent_errors) > 1000:
                self._recent_errors = self._recent_errors[-1000:]
            alpha_ema = 0.01
            self._error_ema = (1 - alpha_ema) * self._error_ema + alpha_ema * error
            self._error_ema_var = (1 - alpha_ema) * self._error_ema_var + alpha_ema * (
                error - self._error_ema
            ) ** 2

            if self._drift.update(error):
                self._boost_remaining = 200
                log.info("Drift detected at observation %d — boosting learning rate", self._count)

            if self._boost_remaining > 0:
                self.lr = self._base_lr * 5.0
                self._boost_remaining -= 1
            else:
                self.lr = self._base_lr

    def score(self, features: dict[str, float]) -> tuple[float, list[dict[str, Any]]]:
        """Score an observation based on reconstruction error."""
        if self._count < 50:
            return 50.0, [{"feature": "insufficient_data", "contribution": 0}]

        with self._lock:
            raw = self._features_to_vector(features)
            x = self._normalize(raw)
            x_clipped = np.clip(x, -5, 5)
            x_scaled = self._sigmoid(x_clipped)

            _, _, out = self._forward(x_scaled)

            per_feature_error = (out - x_scaled) ** 2
            total_error = float(np.mean(per_feature_error))

            std_error = max(math.sqrt(self._error_ema_var), 1e-8)
            z_score = (total_error - self._error_ema) / std_error
            score = max(0.0, min(100.0, 50.0 + z_score * 15.0))

            contributions: list[dict[str, Any]] = []
            active_dims = [
                (name, self._feature_index[name])
                for name in self._feature_names
                if name in features
            ]
            for name, idx in active_dims:
                err = float(per_feature_error[idx])
                if err > self._error_ema * 1.5:
                    contributions.append(
                        {
                            "feature": name,
                            "value": round(float(features.get(name, 0)), 4),
                            "reconstruction_error": round(err, 6),
                            "expected_mean": round(float(self._running_mean[idx]), 4),
                            "z_score": round(
                                abs(float(raw[idx]) - float(self._running_mean[idx]))
                                / max(math.sqrt(float(self._running_var[idx])), 1e-8),
                                2,
                            ),
                            "contribution": round(err / max(total_error, 1e-8) * 100, 1),
                        }
                    )

            contributions.sort(key=lambda c: c["contribution"], reverse=True)
            return round(score, 2), contributions[:10]

    def calibrate_thresholds(self) -> dict[str, float]:
        """Auto-calibrate scoring thresholds based on error distribution."""
        if len(self._recent_errors) < 100:
            return {"p50": 0, "p90": 0, "p95": 0, "p99": 0}
        errors = np.array(self._recent_errors)
        return {
            "p50": round(float(np.percentile(errors, 50)), 6),
            "p90": round(float(np.percentile(errors, 90)), 6),
            "p95": round(float(np.percentile(errors, 95)), 6),
            "p99": round(float(np.percentile(errors, 99)), 6),
            "suggested_review_threshold": round(float(np.percentile(errors, 90)) * 1000, 1),
            "suggested_deny_threshold": round(float(np.percentile(errors, 99)) * 1000, 1),
        }

    def get_stats(self) -> dict[str, Any]:
        base = {
            "type": "autoencoder",
            "observations": self._count,
            "tracked_features": len(self._feature_names),
            "input_dim": self.input_dim,
            "hidden_dim": self.hidden_dim,
            "learning_rate": self.lr,
            "alpha": self.lr,
            "avg_reconstruction_error": round(self._error_ema, 6),
            "error_std": round(math.sqrt(max(self._error_ema_var, 0)), 6),
            "recent_errors_p50": round(
                float(np.median(self._recent_errors)) if self._recent_errors else 0, 6
            ),
            "recent_errors_p99": round(
                float(np.percentile(self._recent_errors, 99))
                if len(self._recent_errors) > 10
                else 0,
                6,
            ),
            "feature_names": self._feature_names[:20],
        }
        base["drift"] = self._drift.get_stats()
        base["thresholds"] = self.calibrate_thresholds()
        return base

    @property
    def _mean(self) -> dict[str, float]:
        """Backward-compatible mean mapping for legacy tests/callers."""
        return {name: float(self._running_mean[idx]) for name, idx in self._feature_index.items()}

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def save(self, path: str) -> None:
        data = {
            "type": "autoencoder",
            "input_dim": self.input_dim,
            "hidden_dim": self.hidden_dim,
            "lr": self.lr,
            "momentum": self.momentum,
            "decay": self.decay,
            "count": self._count,
            "feature_names": self._feature_names,
            "feature_index": self._feature_index,
            "running_mean": self._running_mean.tolist(),
            "mean": self._mean,
            "running_var": self._running_var.tolist(),
            "W_enc": self.W_enc.tolist(),
            "b_enc": self.b_enc.tolist(),
            "W_dec": self.W_dec.tolist(),
            "b_dec": self.b_dec.tolist(),
            "error_ema": self._error_ema,
            "error_ema_var": self._error_ema_var,
            "base_lr": self._base_lr,
            "boost_remaining": self._boost_remaining,
            "drift": {
                "sum": self._drift._sum,
                "min_sum": self._drift._min_sum if self._drift._min_sum != float("inf") else None,
                "count": self._drift._count,
                "running_mean": self._drift._running_mean,
                "drift_detected": self._drift._drift_detected,
                "drift_count": self._drift._drift_count,
                "last_drift_at": self._drift._last_drift_at,
            },
            "saved_at": datetime.now(timezone.utc).isoformat(),
        }
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w") as f:
            json.dump(data, f)

    def load(self, path: str) -> None:
        if not os.path.exists(path):
            return
        with open(path) as f:
            data = json.load(f)
        if data.get("type") != "autoencoder":
            return  # legacy format — start fresh
        self.input_dim = data["input_dim"]
        self.hidden_dim = data["hidden_dim"]
        self.lr = data.get("lr", self.lr)
        self.momentum = data.get("momentum", self.momentum)
        self.decay = data.get("decay", self.decay)
        self._count = data.get("count", 0)
        self._feature_names = data.get("feature_names", [])
        self._feature_index = data.get("feature_index", {})
        if "running_mean" in data:
            self._running_mean = np.array(data["running_mean"], dtype=np.float64)
        else:
            # Legacy format compatibility.
            legacy_mean = data.get("mean", {})
            self._running_mean = np.zeros(self.input_dim, dtype=np.float64)
            for name, value in legacy_mean.items():
                if name in self._feature_index:
                    self._running_mean[self._feature_index[name]] = float(value)
        self._running_var = np.array(data["running_var"], dtype=np.float64)
        self.W_enc = np.array(data["W_enc"], dtype=np.float64)
        self.b_enc = np.array(data["b_enc"], dtype=np.float64)
        self.W_dec = np.array(data["W_dec"], dtype=np.float64)
        self.b_dec = np.array(data["b_dec"], dtype=np.float64)
        self._error_ema = data.get("error_ema", 0.0)
        self._error_ema_var = data.get("error_ema_var", 1.0)
        self._base_lr = data.get("base_lr", self.lr)
        self._boost_remaining = data.get("boost_remaining", 0)
        drift_data = data.get("drift")
        if drift_data:
            self._drift._sum = drift_data.get("sum", 0.0)
            min_sum = drift_data.get("min_sum")
            self._drift._min_sum = float("inf") if min_sum is None else min_sum
            self._drift._count = drift_data.get("count", 0)
            self._drift._running_mean = drift_data.get("running_mean", 0.0)
            self._drift._drift_detected = drift_data.get("drift_detected", False)
            self._drift._drift_count = drift_data.get("drift_count", 0)
            self._drift._last_drift_at = drift_data.get("last_drift_at", 0)


class DriftDetector:
    """Detects concept drift using Page-Hinkley test on reconstruction errors.

    When drift is detected, the autoencoder's learning rate is temporarily
    boosted to adapt faster, then decays back to normal.
    """

    def __init__(self, delta: float = 0.005, threshold: float = 50.0, alpha: float = 0.0001):
        self.delta = delta
        self.threshold = threshold
        self.alpha = alpha
        self._sum = 0.0
        self._min_sum = float("inf")
        self._count = 0
        self._running_mean = 0.0
        self._drift_detected = False
        self._drift_count = 0
        self._last_drift_at = 0

    def update(self, error: float) -> bool:
        """Update with new error. Returns True if drift detected."""
        self._count += 1
        self._running_mean = self._running_mean + (error - self._running_mean) / self._count
        self._sum += error - self._running_mean - self.delta
        self._min_sum = min(self._min_sum, self._sum)

        ph_value = self._sum - self._min_sum
        if ph_value > self.threshold:
            self._drift_detected = True
            self._drift_count += 1
            self._last_drift_at = self._count
            self._sum = 0.0
            self._min_sum = float("inf")
            return True

        self._drift_detected = False
        return False

    def get_stats(self) -> dict:
        return {
            "observations": self._count,
            "drift_count": self._drift_count,
            "last_drift_at": self._last_drift_at,
            "currently_drifting": self._drift_detected,
        }


# Backward compatibility alias
OnlineAnomalyDetector = AdaptiveAutoencoder

_detector = AdaptiveAutoencoder(input_dim=32, hidden_dim=16, learning_rate=0.001)
_STATE_PATH = os.environ.get("ADAPTIVE_STATE_PATH", "./adaptive_state.json")


def get_detector() -> AdaptiveAutoencoder:
    return _detector


def reset_detector() -> AdaptiveAutoencoder:
    global _detector
    _detector = AdaptiveAutoencoder(input_dim=32, hidden_dim=16, learning_rate=0.001)
    return _detector


def init_detector():
    _detector.load(_STATE_PATH)


def save_detector():
    _detector.save(_STATE_PATH)
