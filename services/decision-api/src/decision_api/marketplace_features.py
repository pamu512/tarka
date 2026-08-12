"""Marketplace evaluate feature wiring (KYB, FTID, chargeback, listing, e-hailing)."""

from __future__ import annotations

from typing import Any


def _truthy(val: Any) -> bool:
    if isinstance(val, bool):
        return val
    if isinstance(val, (int, float)):
        return val != 0
    if isinstance(val, str):
        return val.strip().lower() in ("1", "true", "yes", "y")
    return False


def _pick(pl: dict[str, Any], meta: dict[str, Any], *keys: str) -> Any:
    for k in keys:
        if k in pl and pl[k] is not None:
            return pl[k]
        if k in meta and meta[k] is not None:
            return meta[k]
    return None


def apply_marketplace_features(
    features: dict[str, Any],
    payload: dict[str, Any] | None,
    metadata: dict[str, Any] | None,
) -> None:
    """Derive marketplace / multi-sided trust features for vertical pack rules."""
    pl = payload if isinstance(payload, dict) else {}
    meta = metadata if isinstance(metadata, dict) else {}

    gmv = _pick(pl, meta, "seller_gmv_30d", "gmv_30d")
    if gmv is not None:
        try:
            features["seller_gmv_30d"] = float(gmv)
        except (TypeError, ValueError):
            pass

    kyb_state = _pick(pl, meta, "kyb_state", "seller_kyb_state")
    if isinstance(kyb_state, str) and kyb_state.strip():
        features["kyb_state"] = kyb_state.strip().lower()
        features["kyb_unverified"] = features["kyb_state"] in (
            "unverified",
            "collecting",
            "rejected",
        )

    if "kyb_unverified" in meta:
        features["kyb_unverified"] = _truthy(meta["kyb_unverified"])
    if "kyb_sla_breach" in meta or "kyb_sla_breach" in pl:
        features["kyb_sla_breach"] = _truthy(_pick(pl, meta, "kyb_sla_breach"))

    for key in (
        "ftid_intake_mismatch",
        "chargeback_early_alert",
        "brand_protection_hit",
        "off_rail_payment_request",
        "cross_role_same_device",
        "is_location_spoof",
        "worker_auth_failed",
        "delivery_hash_mismatch",
        "is_friendly_fraud_risk",
        "cancel_abuse_high",
        "cancelled_offline_high",
        "refund_abuse_high",
        "selective_theft_high",
    ):
        val = _pick(pl, meta, key)
        if val is not None:
            features[key] = _truthy(val)

    # Derive head flags from numeric bridge scores when host passes raw heads
    heads = _pick(pl, meta, "cancel_heads", "offline_cancel_heads")
    if isinstance(heads, dict):
        for head, feat in (
            ("cancel_abuse", "cancel_abuse_high"),
            ("cancelled_offline", "cancelled_offline_high"),
            ("selective_theft", "selective_theft_high"),
        ):
            try:
                if float(heads.get(head) or 0) >= 0.55:
                    features[feat] = True
            except (TypeError, ValueError):
                pass
    abuse = _pick(pl, meta, "abuse_score", "refund_abuse_score")
    if abuse is not None:
        try:
            if float(abuse) >= 0.7:
                features["refund_abuse_high"] = True
        except (TypeError, ValueError):
            pass

    pair = _pick(pl, meta, "pair_trip_count_24h")
    if pair is not None:
        try:
            features["pair_trip_count_24h"] = int(pair)
        except (TypeError, ValueError):
            pass

    bonus = _pick(pl, meta, "driver_bonus_claim", "bonus_claim_count_24h")
    if bonus is not None:
        try:
            features["driver_bonus_claim"] = int(bonus)
            if features["driver_bonus_claim"] >= 8:
                features["driver_bonus_farm"] = True
        except (TypeError, ValueError):
            pass

    clusters = _pick(pl, meta, "device_cluster_ids")
    if isinstance(clusters, (list, tuple)):
        cleaned = [str(x).strip() for x in clusters if str(x).strip()]
        if cleaned:
            features["device_cluster_ids"] = cleaned[:16]
            features["device_cluster_count"] = len(cleaned)
