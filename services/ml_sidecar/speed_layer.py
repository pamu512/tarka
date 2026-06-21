"""
Real-time bot / fraud signal path: ONNX inference on payloads received from Redis pub/sub.

Subscribes to channel ``tarka:decisions:stream``. Each message body must be JSON with the
five numeric features the baseline model was trained on (see ``train_baseline_xgboost.py``).
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import os
import sys
from typing import Any

import numpy as np
import onnxruntime as ort
import redis.asyncio as redis

CHANNEL = "tarka:decisions:stream"
FEATURE_KEYS = (
    "amount",
    "velocity_1h",
    "velocity_24h",
    "risk_score",
    "time_of_day",
)

logger = logging.getLogger(__name__)


def _default_model_path() -> str:
    return os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "models",
        "baseline_fraud_v1.onnx",
    )


def _load_session(model_path: str) -> ort.InferenceSession:
    if not os.path.isfile(model_path):
        msg = f"ONNX model not found at {model_path}"
        raise FileNotFoundError(msg)
    session = ort.InferenceSession(
        model_path,
        providers=["CPUExecutionProvider"],
    )
    inputs = session.get_inputs()
    if len(inputs) != 1:
        msg = f"expected exactly 1 ONNX input, got {len(inputs)}"
        raise RuntimeError(msg)
    inp = inputs[0]
    if inp.name != "float_input":
        msg = f"unexpected ONNX input name {inp.name!r}, expected 'float_input'"
        raise RuntimeError(msg)
    out_names = {o.name for o in session.get_outputs()}
    if "probabilities" not in out_names:
        msg = f"ONNX model missing 'probabilities' output; have {sorted(out_names)}"
        raise RuntimeError(msg)
    logger.info(
        "onnx_session_ready path=%s inputs=%s outputs=%s",
        model_path,
        [(i.name, i.shape, i.type) for i in inputs],
        [(o.name, o.shape, o.type) for o in session.get_outputs()],
    )
    return session


def _require_float(payload: dict[str, Any], key: str) -> float:
    if key not in payload:
        raise KeyError(key)
    value = payload[key]
    if isinstance(value, bool):
        raise TypeError(f"{key} must be a number, not bool")
    if not isinstance(value, (int, float)):
        raise TypeError(f"{key} must be a number, got {type(value).__name__}")
    out = float(value)
    if not math.isfinite(out):
        raise ValueError(f"{key} must be finite")
    return out


def payload_to_feature_row(payload: dict[str, Any]) -> np.ndarray:
    """Map JSON object to shape (1, 5) float32 tensor matching training feature order."""
    values = [_require_float(payload, k) for k in FEATURE_KEYS]
    arr = np.array([values], dtype=np.float32)
    if arr.shape != (1, 5):
        msg = f"internal shape error: {arr.shape}"
        raise RuntimeError(msg)
    return arr


def run_fraud_inference(
    session: ort.InferenceSession,
    feature_row: np.ndarray,
) -> float:
    """Return fraud class probability (column 1 of ``probabilities`` output)."""
    try:
        outputs = session.run(["probabilities"], {"float_input": feature_row})
    except Exception as exc:
        logger.exception("onnx_inference_failed", exc_info=exc)
        raise
    if not outputs:
        msg = "ONNX session returned no outputs for 'probabilities'"
        raise RuntimeError(msg)
    probs = np.asarray(outputs[0], dtype=np.float64)
    if probs.ndim != 2 or probs.shape[1] < 2:
        msg = f"unexpected probabilities shape {probs.shape}, expected (N, 2)"
        raise RuntimeError(msg)
    fraud_probability = float(probs[0, 1])
    if not math.isfinite(fraud_probability):
        msg = "fraud probability is not finite"
        raise ValueError(msg)
    return fraud_probability


async def _handle_message(session: ort.InferenceSession, raw: bytes | str) -> None:
    text = raw.decode("utf-8") if isinstance(raw, bytes) else raw
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        logger.error("malformed_json payload=%r error=%s", text[:500], exc)
        return

    if not isinstance(parsed, dict):
        logger.error(
            "json_root_not_object type=%s payload=%r",
            type(parsed).__name__,
            text[:500],
        )
        return

    try:
        features = payload_to_feature_row(parsed)
    except KeyError as exc:
        logger.error(
            "missing_feature key=%s keys_present=%s",
            exc.args[0],
            sorted(parsed.keys()),
        )
        return
    except (TypeError, ValueError) as exc:
        logger.error("invalid_feature_values error=%s payload=%r", exc, text[:500])
        return

    try:
        fraud_probability = run_fraud_inference(session, features)
    except Exception:
        return

    if fraud_probability > 0.8:
        logger.critical(
            "FRAUD_THRESHOLD_EXCEEDED fraud_probability=%.6f threshold=0.8 features=%s",
            fraud_probability,
            {k: parsed.get(k) for k in FEATURE_KEYS},
        )


async def _redis_subscribe_loop(session: ort.InferenceSession, redis_url: str) -> None:
    backoff_s = 1.0
    max_backoff_s = 60.0
    while True:
        client: redis.Redis | None = None
        pubsub = None
        try:
            client = redis.from_url(
                redis_url,
                decode_responses=False,
                socket_connect_timeout=10.0,
                socket_timeout=None,
            )
            pubsub = client.pubsub()
            await pubsub.subscribe(CHANNEL)
            logger.info("redis_subscribed channel=%s url=%s", CHANNEL, redis_url)
            backoff_s = 1.0

            while True:
                message = await pubsub.get_message(
                    ignore_subscribe_messages=True,
                    timeout=30.0,
                )
                if message is None:
                    continue
                if message.get("type") != "message":
                    continue
                data = message.get("data")
                if data is None:
                    logger.error("redis_message_missing_data message=%r", message)
                    continue
                await _handle_message(session, data)

        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.exception(
                "redis_loop_error backing_off_s=%.1f error=%s",
                backoff_s,
                exc,
                exc_info=exc,
            )
            await asyncio.sleep(backoff_s)
            backoff_s = min(max_backoff_s, backoff_s * 2.0)
        finally:
            if pubsub is not None:
                try:
                    await pubsub.unsubscribe(CHANNEL)
                    await pubsub.aclose()
                except Exception as close_exc:
                    logger.warning("pubsub_close_error %s", close_exc, exc_info=close_exc)
            if client is not None:
                try:
                    await client.aclose()
                except Exception as close_exc:
                    logger.warning("redis_client_close_error %s", close_exc, exc_info=close_exc)


async def async_main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        stream=sys.stdout,
    )
    model_path = os.environ.get("MODEL_PATH", _default_model_path())
    redis_url = os.environ.get("REDIS_URL", "redis://127.0.0.1:6379/0")

    session = _load_session(model_path)
    await _redis_subscribe_loop(session, redis_url)


def main() -> None:
    asyncio.run(async_main())


if __name__ == "__main__":
    main()
