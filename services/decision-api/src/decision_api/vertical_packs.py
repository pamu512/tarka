from __future__ import annotations

from typing import Any

_VELOCITY_PRESETS: dict[str, list[dict[str, Any]]] = {
    "standard": [
        {"name": "burst_5m", "feature": "event_count_5m", "window_seconds": 300},
        {"name": "hourly_1h", "feature": "event_count_1h", "window_seconds": 3600},
        {"name": "daily_24h", "feature": "event_count_24h", "window_seconds": 86400},
    ],
}

# Kill criteria: do not promote a pack when simulation metrics fall outside bands.
_DEFAULT_KILL: dict[str, Any] = {
    "min_events": 100,
    "min_precision": 0.01,
    "min_recall": 0.01,
    "max_false_positive_rate": 0.95,
    "notes": [
        "Do not promote when low_sample_warning is true.",
        "Do not treat synthetic precision/recall as production KPIs without labeled holdouts.",
    ],
}

_PACKS: dict[str, dict[str, Any]] = {
    "fintech": {
        "name": "Vertical Fintech Starter",
        "version": 1,
        "velocity_presets": "standard",
        "kill_criteria": {
            **_DEFAULT_KILL,
            "min_precision": 0.015,
            "min_recall": 0.02,
        },
        "rules": [
            {
                "id": "fin_high_amount_new_account",
                "when": [
                    {"field": "amount", "op": "gte", "value": 2000},
                    {"field": "account_age_days", "op": "lte", "value": 14},
                ],
                "tags": ["vertical:fintech", "risk:high_amount_new_account"],
                "score_delta": 28,
                "description": "Large transfer from a young account",
            },
            {
                "id": "fin_velocity_spike",
                "when": [{"field": "transaction_count_24h", "op": "gte", "value": 18}],
                "tags": ["vertical:fintech", "risk:velocity_spike"],
                "score_delta": 18,
                "description": "Unusual transaction velocity",
            },
        ],
        "tag_rules": [],
    },
    "ecommerce": {
        "name": "Vertical E-commerce Starter",
        "version": 1,
        "velocity_presets": "standard",
        "kill_criteria": {**_DEFAULT_KILL, "min_precision": 0.015, "min_recall": 0.02},
        "rules": [
            {
                "id": "eco_bot_checkout",
                "when": [
                    {"field": "is_bot", "op": "is_true", "value": True},
                    {"field": "amount", "op": "gte", "value": 150},
                ],
                "tags": ["vertical:ecommerce", "risk:bot_checkout"],
                "score_delta": 22,
                "description": "Checkout attempt with bot signal",
            },
            {
                "id": "eco_multi_geo_velocity",
                "when": [
                    {"field": "distinct_countries_7d", "op": "gte", "value": 3},
                    {"field": "transaction_count_24h", "op": "gte", "value": 12},
                ],
                "tags": ["vertical:ecommerce", "risk:multi_geo_velocity"],
                "score_delta": 20,
                "description": "Cross-border velocity pattern",
            },
        ],
        "tag_rules": [],
    },
    "gaming": {
        "name": "Vertical Gaming Starter",
        "version": 1,
        "velocity_presets": "standard",
        "kill_criteria": {**_DEFAULT_KILL, "min_precision": 0.015, "min_recall": 0.02},
        "rules": [
            {
                "id": "gam_emulator_bot",
                "when": [
                    {"field": "is_emulator", "op": "is_true", "value": True},
                    {"field": "is_bot", "op": "is_true", "value": True},
                ],
                "tags": ["vertical:gaming", "risk:emu_bot"],
                "score_delta": 30,
                "description": "Likely scripted gameplay abuse",
            },
            {
                "id": "gam_night_velocity",
                "when": [
                    {"field": "hour_of_day", "op": "lte", "value": 4},
                    {"field": "transaction_count_24h", "op": "gte", "value": 20},
                ],
                "tags": ["vertical:gaming", "risk:night_velocity"],
                "score_delta": 16,
                "description": "Off-hour farming/abuse pattern",
            },
        ],
        "tag_rules": [],
    },
    "marketplace": {
        "name": "Vertical Marketplace",
        "version": 1,
        "velocity_presets": "standard",
        "kill_criteria": {**_DEFAULT_KILL, "min_precision": 0.015, "min_recall": 0.02},
        "rules": [
            {
                "id": "mkt_shared_device_collusion",
                "when": [
                    {"field": "transaction_count_24h", "op": "gte", "value": 15},
                    {"field": "account_age_days", "op": "lte", "value": 21},
                ],
                "tags": ["vertical:marketplace", "risk:collusion_shared_device"],
                "score_delta": 24,
                "description": "Young account high velocity — collusion / multi-account pattern",
            },
            {
                "id": "mkt_refund_burst",
                "when": [
                    {"field": "is_friendly_fraud_risk", "op": "is_true", "value": True},
                ],
                "tags": ["vertical:marketplace", "risk:refund_burst"],
                "score_delta": 28,
                "description": "Friendly fraud risk — delivery hash mismatch or repeat IP dispute window",
            },
            {
                "id": "mkt_delivery_hash_mismatch",
                "when": [
                    {"field": "delivery_hash_mismatch", "op": "is_true", "value": True},
                ],
                "tags": ["vertical:marketplace", "risk:refund_burst"],
                "score_delta": 24,
                "description": "Delivery confirmation hash mismatch — disputed POD",
            },
            {
                "id": "mkt_review_inflation_proxy",
                "when": [
                    {"field": "transaction_count_24h", "op": "gte", "value": 8},
                    {"field": "amount", "op": "lte", "value": 25},
                    {"field": "account_age_days", "op": "lte", "value": 30},
                ],
                "tags": ["vertical:marketplace", "risk:refund_burst"],
                "score_delta": 18,
                "description": "Low-value high-frequency orders — review inflation proxy",
            },
            {
                "id": "mkt_young_seller_high_payout",
                "when": [
                    {"field": "amount", "op": "gte", "value": 1500},
                    {"field": "account_age_days", "op": "lte", "value": 14},
                ],
                "tags": ["vertical:marketplace", "risk:high_amount_new_account"],
                "score_delta": 26,
                "description": "Young seller requesting large payout",
            },
            {
                "id": "mkt_payout_hold_high_amount",
                "when": [
                    {"field": "amount", "op": "gte", "value": 800},
                    {"field": "transaction_count_24h", "op": "gte", "value": 12},
                ],
                "tags": ["vertical:marketplace", "action:payout_hold", "risk:collusion_shared_device"],
                "score_delta": 30,
                "description": "High payout with elevated velocity — hold pending review",
            },
        ],
        "tag_rules": [],
    },
    "qcommerce": {
        "name": "Vertical Q-Commerce",
        "version": 1,
        "velocity_presets": "standard",
        "kill_criteria": {**_DEFAULT_KILL, "min_precision": 0.015, "min_recall": 0.02},
        "rules": [
            {
                "id": "qcm_promo_farm_velocity",
                "when": [
                    {"field": "transaction_count_24h", "op": "gte", "value": 20},
                    {"field": "amount", "op": "lte", "value": 30},
                ],
                "tags": ["vertical:qcommerce", "risk:promo_farm"],
                "score_delta": 22,
                "description": "Promo farm — high micro-order velocity",
            },
            {
                "id": "qcm_multi_account_bot",
                "when": [
                    {"field": "transaction_count_24h", "op": "gte", "value": 14},
                    {"field": "is_bot", "op": "is_true", "value": True},
                ],
                "tags": ["vertical:qcommerce", "risk:multi_account_partner"],
                "score_delta": 24,
                "description": "Bot-driven multi-account ordering pattern",
            },
            {
                "id": "qcm_referral_burst",
                "when": [
                    {"field": "transaction_count_24h", "op": "gte", "value": 16},
                    {"field": "account_age_days", "op": "lte", "value": 7},
                ],
                "tags": ["vertical:qcommerce", "risk:promo_farm"],
                "score_delta": 20,
                "description": "New account referral/promo burst",
            },
            {
                "id": "qcm_rider_spoof_emulator",
                "when": [
                    {"field": "is_emulator", "op": "is_true", "value": True},
                    {"field": "is_bot", "op": "is_true", "value": True},
                ],
                "tags": ["vertical:qcommerce", "risk:courier_spoof"],
                "score_delta": 28,
                "description": "Emulator/bot rider spoof signal",
            },
            {
                "id": "qcm_payout_delay_promo",
                "when": [
                    {"field": "amount", "op": "gte", "value": 200},
                    {"field": "transaction_count_24h", "op": "gte", "value": 10},
                ],
                "tags": ["vertical:qcommerce", "action:payout_delay", "risk:promo_farm"],
                "score_delta": 22,
                "description": "Promo-linked payout — delay settlement",
            },
        ],
        "tag_rules": [],
    },
    "logistics": {
        "name": "Vertical Logistics",
        "version": 1,
        "velocity_presets": "standard",
        "kill_criteria": {**_DEFAULT_KILL, "min_precision": 0.015, "min_recall": 0.02},
        "rules": [
            {
                "id": "log_multi_account_partner",
                "when": [
                    {"field": "transaction_count_24h", "op": "gte", "value": 18},
                    {"field": "account_age_days", "op": "lte", "value": 14},
                ],
                "tags": ["vertical:logistics", "risk:multi_account_partner"],
                "score_delta": 24,
                "description": "Partner multi-account accept pattern",
            },
            {
                "id": "log_order_accept_velocity",
                "when": [{"field": "transaction_count_24h", "op": "gte", "value": 25}],
                "tags": ["vertical:logistics", "risk:velocity_spike"],
                "score_delta": 18,
                "description": "Abnormal order accept velocity",
            },
            {
                "id": "log_emulator_partner",
                "when": [
                    {"field": "is_emulator", "op": "is_true", "value": True},
                    {"field": "transaction_count_24h", "op": "gte", "value": 8},
                ],
                "tags": ["vertical:logistics", "risk:courier_spoof"],
                "score_delta": 26,
                "description": "Emulator partner device on accept stream",
            },
            {
                "id": "log_payout_hold_high_amount",
                "when": [
                    {"field": "amount", "op": "gte", "value": 500},
                    {"field": "account_age_days", "op": "lte", "value": 21},
                ],
                "tags": ["vertical:logistics", "action:payout_hold", "risk:multi_account_partner"],
                "score_delta": 28,
                "description": "Young partner high payout — hold pending review",
            },
            {
                "id": "log_shared_device_collusion",
                "when": [
                    {"field": "transaction_count_24h", "op": "gte", "value": 12},
                    {"field": "is_bot", "op": "is_true", "value": True},
                ],
                "tags": ["vertical:logistics", "risk:collusion_shared_device"],
                "score_delta": 22,
                "description": "Shared device / bot collusion on partner account",
            },
        ],
        "tag_rules": [],
    },
    "offline_payment": {
        "name": "Vertical Offline Payment / COD",
        "version": 1,
        "velocity_presets": "standard",
        "kill_criteria": {**_DEFAULT_KILL, "min_precision": 0.015, "min_recall": 0.02},
        "rules": [
            {
                "id": "off_cod_high_amount_young",
                "when": [
                    {"field": "is_cod", "op": "is_true", "value": True},
                    {"field": "amount", "op": "gte", "value": 500},
                    {"field": "account_age_days", "op": "lte", "value": 21},
                ],
                "tags": ["vertical:offline_payment", "risk:cod_abuse"],
                "score_delta": 26,
                "description": "COD high-value order from young account",
            },
            {
                "id": "off_cod_velocity_spike",
                "when": [
                    {"field": "is_cod", "op": "is_true", "value": True},
                    {"field": "transaction_count_24h", "op": "gte", "value": 12},
                ],
                "tags": ["vertical:offline_payment", "risk:cod_abuse"],
                "score_delta": 22,
                "description": "COD order velocity spike — refund/COD abuse pattern",
            },
            {
                "id": "off_address_hop_offline",
                "when": [
                    {"field": "is_offline_payment", "op": "is_true", "value": True},
                    {"field": "distinct_countries_7d", "op": "gte", "value": 2},
                    {"field": "transaction_count_24h", "op": "gte", "value": 6},
                ],
                "tags": ["vertical:offline_payment", "risk:address_hop"],
                "score_delta": 24,
                "description": "Offline payment with cross-geo velocity — address hopping",
            },
            {
                "id": "off_cod_micro_burst",
                "when": [
                    {"field": "is_cod", "op": "is_true", "value": True},
                    {"field": "amount", "op": "lte", "value": 75},
                    {"field": "transaction_count_24h", "op": "gte", "value": 10},
                ],
                "tags": ["vertical:offline_payment", "risk:cod_abuse"],
                "score_delta": 20,
                "description": "COD micro-order burst — serial non-delivery pattern",
            },
            {
                "id": "off_payout_hold_cod_high",
                "when": [
                    {"field": "is_offline_payment", "op": "is_true", "value": True},
                    {"field": "amount", "op": "gte", "value": 800},
                    {"field": "transaction_count_24h", "op": "gte", "value": 8},
                ],
                "tags": [
                    "vertical:offline_payment",
                    "risk:cod_abuse",
                    "action:payout_hold",
                ],
                "score_delta": 28,
                "description": "High offline/COD payout with velocity — hold pending review",
            },
        ],
        "tag_rules": [],
    },
    "food_delivery": {
        "name": "Vertical Food Delivery",
        "version": 1,
        "velocity_presets": "standard",
        "kill_criteria": {**_DEFAULT_KILL, "min_precision": 0.015, "min_recall": 0.02},
        "rules": [
            {
                "id": "fd_refund_cancel_burst",
                "when": [
                    {"field": "is_friendly_fraud_risk", "op": "is_true", "value": True},
                ],
                "tags": ["vertical:food_delivery", "risk:refund_burst"],
                "score_delta": 26,
                "description": "Friendly fraud risk — delivery hash mismatch or repeat IP dispute window",
            },
            {
                "id": "fd_delivery_hash_mismatch",
                "when": [
                    {"field": "delivery_hash_mismatch", "op": "is_true", "value": True},
                ],
                "tags": ["vertical:food_delivery", "risk:refund_burst"],
                "score_delta": 22,
                "description": "POD hash mismatch on disputed delivery",
            },
            {
                "id": "fd_courier_spoof_emulator",
                "when": [
                    {"field": "is_emulator", "op": "is_true", "value": True},
                    {"field": "is_bot", "op": "is_true", "value": True},
                ],
                "tags": ["vertical:food_delivery", "risk:courier_spoof"],
                "score_delta": 28,
                "description": "Courier spoof — emulator/bot delivery signal",
            },
            {
                "id": "fd_diner_merchant_velocity",
                "when": [
                    {"field": "transaction_count_24h", "op": "gte", "value": 15},
                    {"field": "distinct_countries_7d", "op": "gte", "value": 2},
                ],
                "tags": ["vertical:food_delivery", "risk:collusion_shared_device"],
                "score_delta": 22,
                "description": "Diner–merchant velocity across geos",
            },
            {
                "id": "fd_promo_farm",
                "when": [
                    {"field": "transaction_count_24h", "op": "gte", "value": 18},
                    {"field": "amount", "op": "lte", "value": 20},
                    {"field": "account_age_days", "op": "lte", "value": 10},
                ],
                "tags": ["vertical:food_delivery", "risk:promo_farm"],
                "score_delta": 24,
                "description": "Promo farm on new diner account",
            },
            {
                "id": "fd_payout_hold_courier",
                "when": [
                    {"field": "amount", "op": "gte", "value": 300},
                    {"field": "is_emulator", "op": "is_true", "value": True},
                ],
                "tags": ["vertical:food_delivery", "action:payout_hold", "risk:courier_spoof"],
                "score_delta": 30,
                "description": "Courier payout with spoof signal — hold pending review",
            },
        ],
        "tag_rules": [],
    },
}


def list_vertical_packs() -> dict[str, dict[str, Any]]:
    return {
        k: {
            "name": v["name"],
            "rules": len(v.get("rules", [])),
            "version": v.get("version", 1),
            "has_kill_criteria": bool(v.get("kill_criteria")),
        }
        for k, v in _PACKS.items()
    }


def evaluate_kill_criteria(
    metrics: dict[str, Any],
    kill: dict[str, Any] | None,
    *,
    events_evaluated: int,
) -> dict[str, Any]:
    """Return promote gate from simulation metrics vs pack kill_criteria."""
    criteria = dict(kill or _DEFAULT_KILL)
    blockers: list[str] = []
    precision = float(metrics.get("precision") or 0.0)
    recall = float(metrics.get("recall") or 0.0)
    fpr = float(metrics.get("false_positive_rate") or metrics.get("fpr") or 0.0)
    min_events = int(criteria.get("min_events") or 100)
    if events_evaluated < min_events:
        blockers.append(f"events_evaluated<{min_events}")
    if precision < float(criteria.get("min_precision") or 0.0):
        blockers.append("precision_below_min")
    if recall < float(criteria.get("min_recall") or 0.0):
        blockers.append("recall_below_min")
    max_fpr = criteria.get("max_false_positive_rate")
    if max_fpr is not None and fpr > float(max_fpr):
        blockers.append("false_positive_rate_above_max")
    return {
        "promote_allowed": len(blockers) == 0,
        "blockers": blockers,
        "kill_criteria": criteria,
        "notes": list(criteria.get("notes") or []),
    }


def get_vertical_pack(name: str) -> dict[str, Any] | None:
    pack = _PACKS.get(name.lower())
    if not pack:
        return None
    vp_key = pack.get("velocity_presets")
    presets = _VELOCITY_PRESETS.get(str(vp_key), []) if vp_key else []
    return {
        "name": pack["name"],
        "version": pack.get("version", 1),
        "velocity_presets": presets,
        "rules": [dict(r) for r in pack.get("rules", [])],
        "tag_rules": [dict(r) for r in pack.get("tag_rules", [])],
        "kill_criteria": dict(pack.get("kill_criteria") or _DEFAULT_KILL),
    }
