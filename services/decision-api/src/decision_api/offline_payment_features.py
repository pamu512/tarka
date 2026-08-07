"""COD / offline payment feature wiring for evaluate (Marketplace B1)."""

from __future__ import annotations

from typing import Any

_OFFLINE_METHODS = frozenset({"offline", "store_pickup", "pay_at_store", "cash"})
_COD_METHODS = frozenset({"cod", "cash_on_delivery", "cash"})


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
