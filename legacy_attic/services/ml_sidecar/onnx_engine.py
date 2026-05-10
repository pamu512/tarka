"""
ONNX Runtime inference for fraud scoring.

Expects a baseline export with a single float input and a ``probabilities`` output
(two-class); ``predict`` returns the positive-class probability.
"""

from __future__ import annotations

import logging
import math
from pathlib import Path
from typing import Final

import numpy as np
import onnxruntime as ort

logger = logging.getLogger(__name__)

EXPECTED_FEATURES = 5


class BotDetectionModel:
    """
    Placeholder bot/automation risk scorer.

    Reserved for a future ONNX or rules-backed implementation. The current
    ``predict`` contract matches the eventual shape: async scoring from a single
    monetary ``amount`` into a probability-like score in ``[0.0, 1.0]``.
    """

    _PLACEHOLDER_SCORE: Final[float] = 0.95

    def __init__(self) -> None:
        """Initialize placeholder bot-detection state (no external resources yet)."""
        logger.info("bot_detection_model_initialized mode=placeholder")

    async def predict(self, amount: float) -> float:
        """
        Score transaction ``amount`` for bot-like activity likelihood.

        Parameters
        ----------
        amount :
            Transaction amount; must be a finite float (``NaN`` / infinities rejected).

        Returns
        -------
        float
            Placeholder constant ``0.95`` until a real model is wired.
        """
        if isinstance(amount, bool):
            raise ValueError("amount must be numeric, not bool")
        if not isinstance(amount, (int, float)):
            raise TypeError(f"amount must be int or float, got {type(amount).__name__}")
        if not math.isfinite(float(amount)):
            raise ValueError("amount must be finite")

        return self._PLACEHOLDER_SCORE


class FraudPredictor:
    def __init__(self, model_path: str = "models/baseline_fraud_v1.onnx") -> None:
        raw = Path(model_path)
        resolved = raw if raw.is_file() else Path(__file__).resolve().parent / raw
        if not resolved.is_file():
            raise FileNotFoundError(
                f"Model not found at {resolved}. Generate or mount the ONNX artifact first.",
            )

        self._model_path = resolved
        self.session = ort.InferenceSession(
            str(resolved),
            providers=["CPUExecutionProvider"],
        )
        inputs = self.session.get_inputs()
        if len(inputs) != 1:
            raise RuntimeError(f"expected 1 model input, found {len(inputs)}")
        self.input_name = inputs[0].name

        outputs = self.session.get_outputs()
        prob_names = [o.name for o in outputs if o.name == "probabilities"]
        if not prob_names:
            raise RuntimeError(
                "model missing 'probabilities' output; "
                f"have {[o.name for o in outputs]}",
            )
        self._probabilities_name = prob_names[0]

        logger.info(
            "fraud_predictor_ready path=%s input=%s prob_output=%s",
            resolved,
            self.input_name,
            self._probabilities_name,
        )

    @property
    def model_path(self) -> Path:
        return self._model_path

    def predict(self, features: list[float]) -> float:
        """
        Features: ``[amount, velocity_1h, velocity_24h, risk_score, time_of_day]``.
        Returns fraud probability in ``[0.0, 1.0]`` from ``probabilities[:, 1]``.
        """
        if len(features) != EXPECTED_FEATURES:
            raise ValueError(f"expected {EXPECTED_FEATURES} features, got {len(features)}")

        for i, v in enumerate(features):
            if isinstance(v, bool):
                raise ValueError(f"feature at index {i} must be numeric, not bool")
            if not isinstance(v, (int, float)):
                raise ValueError(
                    f"feature at index {i} must be int or float, got {type(v).__name__}",
                )
            if not math.isfinite(float(v)):
                raise ValueError(f"feature at index {i} must be finite, got {v!r}")

        input_data = np.array([features], dtype=np.float32)
        outputs = self.session.run(
            [self._probabilities_name],
            {self.input_name: input_data},
        )
        if not outputs:
            raise RuntimeError("ONNX session returned empty output list")

        probs = np.asarray(outputs[0], dtype=np.float64)
        if probs.ndim != 2 or probs.shape[1] < 2:
            raise RuntimeError(
                f"unexpected probabilities shape {getattr(probs, 'shape', None)}, expected (N, 2)",
            )
        fraud_probability = float(probs[0, 1])
        if not math.isfinite(fraud_probability):
            raise RuntimeError("non-finite fraud probability from model")
        return fraud_probability
