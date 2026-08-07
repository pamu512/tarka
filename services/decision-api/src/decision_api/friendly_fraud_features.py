"""Friendly-fraud feature wiring for evaluate (metadata-first, no audit DB)."""

from __future__ import annotations

from typing import Any

_DELIVERY_HASH_KEYS = (
    "delivery_confirmation_hash",
    "pod_hash",
    "proof_of_delivery_hash",
)
_EXPECTED_HASH_KEYS = ("expected_delivery_hash", "expected_delivery_confirmation_hash")
_PRIOR_ORDERS_KEYS = ("prior_successful_orders_same_ip",)
_DISPUTE_HOURS_KEYS = ("dispute_hours_since_delivery",)
_DELIVERY_WINDOW_HOURS = 72


def _norm_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _norm_hash(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        return None
    s = value.strip().lower()
    return s or None


def _first_hash(source: dict[str, Any], keys: tuple[str, ...]) -> str | None:
    for key in keys:
        h = _norm_hash(source.get(key))
        if h:
            return h
    return None


def _safe_int(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str):
        s = value.strip()
        if not s:
            return None
        try:
            return int(s)
        except ValueError:
            return None
    return None


def _safe_float(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        s = value.strip()
        if not s:
            return None
        try:
            return float(s)
        except ValueError:
            return None
    return None


def _lookup(sources: tuple[dict[str, Any], ...], keys: tuple[str, ...]) -> Any:
    for src in sources:
        for key in keys:
            if key in src:
                return src[key]
    return None


def apply_friendly_fraud_features(
    features: dict[str, Any],
    metadata: dict[str, Any] | None,
    payload: dict[str, Any] | None,
) -> None:
    """Merge delivery/dispute friendly-fraud signals into rule features."""
    meta = _norm_dict(metadata)
    pl = _norm_dict(payload)
    sources = (meta, pl)

    actual_hash = _first_hash(meta, _DELIVERY_HASH_KEYS) or _first_hash(pl, _DELIVERY_HASH_KEYS)
    expected_hash = _first_hash(meta, _EXPECTED_HASH_KEYS) or _first_hash(
        pl, _EXPECTED_HASH_KEYS
    )

    if actual_hash is not None and expected_hash is not None:
        features["delivery_hash_mismatch"] = actual_hash != expected_hash

    prior_raw = _lookup(sources, _PRIOR_ORDERS_KEYS)
    prior_orders = _safe_int(prior_raw)
    if prior_orders is not None:
        features["prior_successful_orders_same_ip"] = max(prior_orders, 0)

    dispute_hours_raw = _lookup(sources, _DISPUTE_HOURS_KEYS)
    dispute_hours = _safe_float(dispute_hours_raw)
    if dispute_hours is not None:
        features["dispute_within_delivery_window"] = (
            0 <= dispute_hours <= _DELIVERY_WINDOW_HOURS
        )

    hash_mismatch = features.get("delivery_hash_mismatch") is True
    prior = features.get("prior_successful_orders_same_ip")
    within_window = features.get("dispute_within_delivery_window") is True
    if isinstance(prior, int) and prior >= 2 and within_window:
        features["is_friendly_fraud_risk"] = True
    elif hash_mismatch:
        features["is_friendly_fraud_risk"] = True
    elif "delivery_hash_mismatch" in features or "dispute_within_delivery_window" in features:
        features["is_friendly_fraud_risk"] = False
