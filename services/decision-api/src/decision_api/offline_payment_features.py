"""COD / offline payment feature wiring for evaluate (Marketplace B1)."""

from __future__ import annotations

from typing import Any

_OFFLINE_METHODS = frozenset({"offline", "store_pickup", "pay_at_store", "cash"})
_COD_METHODS = frozenset({"cod", "cash_on_delivery", "cash"})


def _safe_float(val: Any) -> float | None:
    if isinstance(val, bool) or val is None:
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


def _safe_int(val: Any) -> int | None:
    if isinstance(val, bool) or val is None:
        return None
    try:
        return int(val)
    except (TypeError, ValueError):
        return None


def apply_offline_payment_features(
    features: dict[str, Any],
    payload: dict[str, Any] | None,
    metadata: dict[str, Any] | None,
) -> None:
    """Merge payment_method / is_cod / is_offline_payment into rule features."""
    pl = payload if isinstance(payload, dict) else {}
    meta = metadata if isinstance(metadata, dict) else {}
    pm = pl.get("payment_method") or meta.get("payment_method")
    if isinstance(pm, str) and pm.strip():
        features["payment_method"] = pm.strip().lower()
        features["is_cod"] = features["payment_method"] in _COD_METHODS
        features["is_offline_payment"] = features["is_cod"] or features[
            "payment_method"
        ] in _OFFLINE_METHODS
    if isinstance(meta.get("is_cod"), bool):
        features["is_cod"] = meta["is_cod"]
    if isinstance(meta.get("is_offline_payment"), bool):
        features["is_offline_payment"] = meta["is_offline_payment"]

    # Host Downstream COD abuse signals (fake-order + theft — Q6)
    cod_block = meta.get("cod") if isinstance(meta.get("cod"), dict) else {}
    for src in (cod_block, meta, pl):
        rr = _safe_float(src.get("cod_refusal_rate_30d") or src.get("refusal_rate_30d"))
        if rr is not None:
            features["cod_refusal_rate_30d"] = max(0.0, min(1.0, rr))
            features["cod_refusal_high"] = features["cod_refusal_rate_30d"] >= 0.35
        jig = _safe_int(src.get("address_jig_count_7d") or src.get("address_jig_count"))
        if jig is not None:
            features["address_jig_count_7d"] = max(0, jig)
            features["address_jig_high"] = features["address_jig_count_7d"] >= 4
        addrs = _safe_int(
            src.get("distinct_delivery_addresses_7d")
            or src.get("distinct_addresses_7d")
        )
        if addrs is not None:
            features["distinct_delivery_addresses_7d"] = max(0, addrs)
            features["address_hop_high"] = features["distinct_delivery_addresses_7d"] >= 5
        theft = src.get("selective_theft_suspected")
        if isinstance(theft, bool):
            features["selective_theft_high"] = theft
        elif theft is not None:
            features["selective_theft_high"] = str(theft).strip().lower() in (
                "1",
                "true",
                "yes",
            )
