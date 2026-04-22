from __future__ import annotations
from typing import Any

"""Pure-Python heuristic scoring and feature extraction (no FastAPI).

Used by ``main`` and by lightweight callers (e.g. ``scripts/benchmarks/drift_score_smoke``)
that must not import the full ASGI stack.
"""
# Training / ONNX vector order (documentation parity with extract_feature_vector).
FEATURE_ORDER = [
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

NORM_DIVISORS = [10_000, 24, 1, 1, 1, 1, 100, 10, 365]


def safe_float(val: Any, default: float = 0.0) -> float:
    if val is None:
        return default
    if isinstance(val, bool):
        return 1.0 if val else 0.0
    try:
        return float(val)
    except (TypeError, ValueError):
        return default


def extract_feature_vector(features: dict[str, Any]) -> list[float]:
    """Build a normalised 9-element feature vector matching training order.

    Feature mapping (with aliases for backward compatibility):
        0  amount             / 10_000
        1  hour_of_day        / 24
        2  is_new_device      0/1  (also accepts ``new_device``)
        3  is_vpn             0/1
        4  is_emulator        0/1
        5  is_bot             0/1
        6  transaction_count_24h / 100
        7  distinct_countries_7d / 10
        8  account_age_days   / 365
    """
    new_device = features.get("is_new_device")
    if new_device is None:
        new_device = features.get("new_device")

    raw = [
        safe_float(features.get("amount")),
        safe_float(features.get("hour_of_day")),
        safe_float(new_device),
        safe_float(features.get("is_vpn")),
        safe_float(features.get("is_emulator")),
        safe_float(features.get("is_bot")),
        safe_float(features.get("transaction_count_24h")),
        safe_float(features.get("distinct_countries_7d")),
        safe_float(features.get("account_age_days")),
    ]
    return [v / d for v, d in zip(raw, NORM_DIVISORS)]


def heuristic_score(features: dict[str, Any]) -> float:
    s = 10.0
    amt = safe_float(features.get("amount"))
    if amt > 5_000:
        s += 15
    if amt > 15_000:
        s += 20
    if amt > 50_000:
        s += 10

    if safe_float(features.get("is_new_device") or features.get("new_device")) > 0:
        s += 10
    if safe_float(features.get("is_emulator")) > 0:
        s += 15
    if safe_float(features.get("is_bot")) > 0:
        s += 20
    if safe_float(features.get("is_vpn")) > 0:
        s += 5

    hour = safe_float(features.get("hour_of_day"), default=-1)
    if 0 <= hour <= 5 or hour >= 22:
        s += 8

    tx_count = safe_float(features.get("transaction_count_24h"))
    if tx_count > 20:
        s += 10
    elif tx_count > 10:
        s += 5

    countries = safe_float(features.get("distinct_countries_7d"))
    if countries >= 4:
        s += 10
    elif countries >= 2:
        s += 3

    age = safe_float(features.get("account_age_days"), default=999)
    if age < 7:
        s += 12
    elif age < 30:
        s += 5

    return max(0.0, min(100.0, s))
