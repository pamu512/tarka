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

    actual_hash = _first_hash(meta, _DELIVERY_HASH_KEYS) or _first_hash(
        pl, _DELIVERY_HASH_KEYS
    )
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

    # POD integrity (host Downstream fields — no carrier LIVE)
    pod_block = meta.get("pod") if isinstance(meta.get("pod"), dict) else {}
    pod_sources = (pod_block, meta, pl)

    def _truthy_pod(keys: tuple[str, ...]) -> bool | None:
        for src in pod_sources:
            for key in keys:
                if key not in src:
                    continue
                val = src[key]
                if isinstance(val, bool):
                    return val
                if isinstance(val, (int, float)):
                    return val != 0
                if isinstance(val, str):
                    return val.strip().lower() in (
                        "1",
                        "true",
                        "yes",
                        "y",
                        "fail",
                        "miss",
                        "mismatch",
                    )
        return None

    geo = _truthy_pod(("pod_geofence_miss", "geofence_miss", "pod_geofence_failed"))
    if geo is not None:
        features["pod_geofence_miss"] = geo
    otp = _truthy_pod(("pod_otp_fail", "otp_fail", "pod_otp_failed"))
    if otp is not None:
        features["pod_otp_fail"] = otp
    photo = _truthy_pod(
        ("pod_photo_hash_mismatch", "photo_hash_mismatch", "pod_photo_mismatch")
    )
    if photo is not None:
        features["pod_photo_hash_mismatch"] = photo
    elif actual_hash is not None and expected_hash is not None:
        # reuse delivery hash mismatch as photo-POD signal when host uses same fields
        features["pod_photo_hash_mismatch"] = actual_hash != expected_hash

    pod_fail = any(
        features.get(k) is True
        for k in ("pod_geofence_miss", "pod_otp_fail", "pod_photo_hash_mismatch")
    )
    if pod_fail:
        features["pod_integrity_fail"] = True
        features["is_friendly_fraud_risk"] = True

    hash_mismatch = features.get("delivery_hash_mismatch") is True
    prior = features.get("prior_successful_orders_same_ip")
    within_window = features.get("dispute_within_delivery_window") is True
    if isinstance(prior, int) and prior >= 2 and within_window:
        features["is_friendly_fraud_risk"] = True
    elif hash_mismatch:
        features["is_friendly_fraud_risk"] = True
    elif (
        "delivery_hash_mismatch" in features
        or "dispute_within_delivery_window" in features
    ) and not pod_fail:
        features["is_friendly_fraud_risk"] = False
