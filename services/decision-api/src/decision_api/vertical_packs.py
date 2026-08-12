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
                "tags": [
                    "vertical:marketplace",
                    "action:payout_hold",
                    "risk:collusion_shared_device",
                ],
                "score_delta": 30,
                "description": "High payout with elevated velocity — hold pending review",
            },
            {
                "id": "mkt_kyb_unverified_high_gmv",
                "when": [
                    {"field": "seller_gmv_30d", "op": "gte", "value": 5000},
                    {"field": "kyb_unverified", "op": "is_true", "value": True},
                ],
                "tags": [
                    "vertical:marketplace",
                    "risk:kyb_unverified_high_volume",
                    "action:kyb_collect",
                    "action:suspend_sales",
                ],
                "score_delta": 32,
                "description": "High-GMV seller without KYB — INFORM-shaped collect + suspend sales",
            },
            {
                "id": "mkt_kyb_sla_breach",
                "when": [
                    {"field": "kyb_sla_breach", "op": "is_true", "value": True},
                ],
                "tags": [
                    "vertical:marketplace",
                    "risk:kyb_sla_breach",
                    "action:suspend_sales",
                ],
                "score_delta": 28,
                "description": "Seller KYB collection SLA breached — suspend sales",
            },
            {
                "id": "mkt_ftid_intake_mismatch",
                "when": [
                    {"field": "ftid_intake_mismatch", "op": "is_true", "value": True},
                ],
                "tags": [
                    "vertical:marketplace",
                    "risk:ftid",
                    "action:refund_hold",
                ],
                "score_delta": 34,
                "description": "Carrier delivered but intake hash/weight mismatch — hold refund (FTID)",
            },
            {
                "id": "mkt_chargeback_early_alert",
                "when": [
                    {"field": "chargeback_early_alert", "op": "is_true", "value": True},
                ],
                "tags": [
                    "vertical:marketplace",
                    "risk:friendly_fraud",
                    "action:dispute_open",
                ],
                "score_delta": 36,
                "description": "Ethoca/Verifi-class early alert — open dispute / representment path",
            },
            {
                "id": "mkt_listing_brand_hit",
                "when": [
                    {"field": "brand_protection_hit", "op": "is_true", "value": True},
                ],
                "tags": [
                    "vertical:marketplace",
                    "risk:counterfeit",
                    "action:listing_takedown",
                ],
                "score_delta": 30,
                "description": "Brand-protection connector hit — listing risk / takedown",
            },
            {
                "id": "mkt_listing_risk_high",
                "when": [
                    {"field": "listing_risk_high", "op": "is_true", "value": True},
                ],
                "tags": [
                    "vertical:marketplace",
                    "risk:live_commerce",
                    "risk:counterfeit",
                    "action:hard_challenge",
                ],
                "score_delta": 28,
                "description": "Live-commerce / listing_risk engine elevated",
            },
            {
                "id": "listing_risk_engine",
                "when": [
                    {"field": "listing_risk_score", "op": "gte", "value": 40},
                ],
                "tags": ["vertical:marketplace", "risk:listing"],
                "score_delta": 12,
                "description": "Listing risk engine score contribution",
            },
            {
                "id": "mkt_off_rail_payment",
                "when": [
                    {
                        "field": "off_rail_payment_request",
                        "op": "is_true",
                        "value": True,
                    },
                ],
                "tags": [
                    "vertical:marketplace",
                    "risk:off_rail_payment",
                    "action:hard_challenge",
                ],
                "score_delta": 26,
                "description": "Payment instruction left in-app rail (PIX/UPI/M-Pesa social-eng)",
            },
            {
                "id": "mkt_lifecycle_risk_high",
                "when": [
                    {"field": "lifecycle_risk_high", "op": "is_true", "value": True},
                ],
                "tags": [
                    "vertical:marketplace",
                    "risk:lifecycle",
                    "action:refund_hold",
                ],
                "score_delta": 20,
                "description": "Lifecycle sequence engine elevated (consumes depth score)",
            },
            {
                "id": "mkt_ring_score_high",
                "when": [
                    {"field": "ring_score_high", "op": "is_true", "value": True},
                ],
                "tags": [
                    "vertical:marketplace",
                    "risk:collusion_shared_device",
                    "action:hard_challenge",
                ],
                "score_delta": 20,
                "description": "Multi-party ring engine elevated (consumes depth score)",
            },
            {
                "id": "mkt_seller_trajectory_high",
                "when": [
                    {"field": "seller_trajectory_high", "op": "is_true", "value": True},
                ],
                "tags": [
                    "vertical:marketplace",
                    "risk:seller_trajectory",
                    "action:payout_hold",
                ],
                "score_delta": 18,
                "description": "Seller trajectory changepoint engine elevated",
            },
            {
                "id": "mkt_ftid_hold",
                "when": [
                    {"field": "ftid_refund_hold", "op": "is_true", "value": True},
                ],
                "tags": [
                    "vertical:marketplace",
                    "risk:ftid",
                    "action:refund_hold",
                ],
                "score_delta": 22,
                "description": "FTID causal gate requires refund hold",
            },
            {
                "id": "mkt_promo_econ_high",
                "when": [
                    {"field": "promo_econ_high", "op": "is_true", "value": True},
                ],
                "tags": [
                    "vertical:marketplace",
                    "risk:promo_farm",
                    "action:hard_challenge",
                ],
                "score_delta": 16,
                "description": "Promo economics fusion elevated",
            },
            {
                "id": "mkt_representment_weak",
                "when": [
                    {"field": "representment_weak", "op": "is_true", "value": True},
                ],
                "tags": [
                    "vertical:marketplace",
                    "risk:dispute_representment",
                    "action:dispute_evidence_gap",
                ],
                "score_delta": 14,
                "description": "Dispute representment pack weak vs reason code",
            },
            {
                "id": "mkt_case_karma_high",
                "when": [
                    {"field": "case_karma_high", "op": "is_true", "value": True},
                ],
                "tags": [
                    "vertical:marketplace",
                    "risk:refund_burst",
                    "action:hard_challenge",
                ],
                "score_delta": 26,
                "description": "Case karma — elevated repeat refund / dispute loss",
            },
            {
                "id": "mkt_depth_fusion_high",
                "when": [
                    {"field": "depth_fusion_high", "op": "is_true", "value": True},
                ],
                "tags": [
                    "vertical:marketplace",
                    "risk:depth_fusion",
                    "action:hard_challenge",
                ],
                "score_delta": 28,
                "description": "Multi-signal depth fusion elevated (lifecycle×ring / FTID pairs)",
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
                "tags": [
                    "vertical:qcommerce",
                    "action:payout_delay",
                    "risk:promo_farm",
                ],
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
                "tags": [
                    "vertical:logistics",
                    "action:payout_hold",
                    "risk:multi_account_partner",
                ],
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
            {
                "id": "log_ftid_refund_hold",
                "when": [
                    {"field": "ftid_refund_hold", "op": "is_true", "value": True},
                ],
                "tags": [
                    "vertical:logistics",
                    "risk:ftid",
                    "action:refund_hold",
                ],
                "score_delta": 32,
                "description": "FTID causal gate — hold refund until intake matches",
            },
            {
                "id": "log_pod_geofence_miss",
                "when": [
                    {"field": "pod_geofence_miss", "op": "is_true", "value": True},
                ],
                "tags": [
                    "vertical:logistics",
                    "risk:friendly_fraud",
                    "action:hard_challenge",
                ],
                "score_delta": 26,
                "description": "POD geofence miss on delivery confirmation",
            },
            {
                "id": "log_pod_otp_fail",
                "when": [
                    {"field": "pod_otp_fail", "op": "is_true", "value": True},
                ],
                "tags": [
                    "vertical:logistics",
                    "risk:friendly_fraud",
                    "action:hard_challenge",
                ],
                "score_delta": 28,
                "description": "POD OTP failure — recipient verification failed",
            },
            {
                "id": "log_pod_photo_mismatch",
                "when": [
                    {
                        "field": "pod_photo_hash_mismatch",
                        "op": "is_true",
                        "value": True,
                    },
                ],
                "tags": [
                    "vertical:logistics",
                    "risk:friendly_fraud",
                    "action:refund_hold",
                ],
                "score_delta": 30,
                "description": "POD photo hash mismatch vs expected delivery artifact",
            },
            {
                "id": "log_pod_integrity_fail",
                "when": [
                    {"field": "pod_integrity_fail", "op": "is_true", "value": True},
                ],
                "tags": [
                    "vertical:logistics",
                    "risk:friendly_fraud",
                    "action:hard_challenge",
                ],
                "score_delta": 24,
                "description": "Combined POD integrity failure",
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
            {
                "id": "off_cod_refusal_high",
                "when": [
                    {"field": "is_cod", "op": "is_true", "value": True},
                    {"field": "cod_refusal_high", "op": "is_true", "value": True},
                ],
                "tags": [
                    "vertical:offline_payment",
                    "risk:cod_abuse",
                    "action:hard_challenge",
                ],
                "score_delta": 28,
                "description": "Elevated COD refusal rate — fake-order pattern",
            },
            {
                "id": "off_address_jig_high",
                "when": [
                    {"field": "address_jig_high", "op": "is_true", "value": True},
                ],
                "tags": [
                    "vertical:offline_payment",
                    "risk:address_hop",
                    "action:hard_challenge",
                ],
                "score_delta": 26,
                "description": "Address jigging — slight variants to evade COD filters",
            },
            {
                "id": "off_address_hop_high",
                "when": [
                    {"field": "address_hop_high", "op": "is_true", "value": True},
                    {"field": "is_cod", "op": "is_true", "value": True},
                ],
                "tags": [
                    "vertical:offline_payment",
                    "risk:address_hop",
                    "action:hard_challenge",
                ],
                "score_delta": 24,
                "description": "Many distinct COD delivery addresses in short window",
            },
            {
                "id": "off_selective_theft",
                "when": [
                    {"field": "selective_theft_high", "op": "is_true", "value": True},
                    {"field": "is_cod", "op": "is_true", "value": True},
                ],
                "tags": [
                    "vertical:offline_payment",
                    "risk:cod_abuse",
                    "action:payout_hold",
                ],
                "score_delta": 30,
                "description": "Selective COD theft / non-delivery suspected",
            },
            {
                "id": "off_rail_payment_request",
                "when": [
                    {
                        "field": "off_rail_payment_request",
                        "op": "is_true",
                        "value": True,
                    },
                ],
                "tags": [
                    "vertical:offline_payment",
                    "risk:off_rail_payment",
                    "action:hard_challenge",
                ],
                "score_delta": 28,
                "description": "Off-rail payment request outside platform rails",
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
                "tags": [
                    "vertical:food_delivery",
                    "action:payout_hold",
                    "risk:courier_spoof",
                ],
                "score_delta": 30,
                "description": "Courier payout with spoof signal — hold pending review",
            },
            {
                "id": "fd_cancel_abuse_head",
                "when": [
                    {"field": "cancel_abuse_high", "op": "is_true", "value": True},
                ],
                "tags": [
                    "vertical:food_delivery",
                    "risk:refund_burst",
                    "action:hard_challenge",
                ],
                "score_delta": 28,
                "description": "Offline-cancel bridge head elevated — cancel abuse pattern",
            },
            {
                "id": "fd_cancelled_offline_head",
                "when": [
                    {"field": "cancelled_offline_high", "op": "is_true", "value": True},
                ],
                "tags": [
                    "vertical:food_delivery",
                    "risk:courier_spoof",
                    "action:hard_challenge",
                ],
                "score_delta": 30,
                "description": "Ghost delivery / cancelled-offline completion signal",
            },
            {
                "id": "fd_ftid_intake_mismatch",
                "when": [
                    {"field": "ftid_intake_mismatch", "op": "is_true", "value": True},
                ],
                "tags": [
                    "vertical:food_delivery",
                    "risk:ftid",
                    "action:refund_hold",
                ],
                "score_delta": 32,
                "description": "Return intake mismatch — hold refund (FTID-shaped)",
            },
            {
                "id": "fd_cross_role_same_device",
                "when": [
                    {"field": "cross_role_same_device", "op": "is_true", "value": True},
                ],
                "tags": [
                    "vertical:food_delivery",
                    "risk:collusion_shared_device",
                    "action:hard_challenge",
                ],
                "score_delta": 34,
                "description": "Same device on diner + courier roles — collusion challenge",
            },
            {
                "id": "fd_off_rail_payment",
                "when": [
                    {
                        "field": "off_rail_payment_request",
                        "op": "is_true",
                        "value": True,
                    },
                ],
                "tags": [
                    "vertical:food_delivery",
                    "risk:off_rail_payment",
                    "action:hard_challenge",
                ],
                "score_delta": 26,
                "description": "Payment instruction left in-app rail",
            },
            {
                "id": "fd_refund_abuse_high",
                "when": [
                    {"field": "refund_abuse_high", "op": "is_true", "value": True},
                ],
                "tags": [
                    "vertical:food_delivery",
                    "risk:refund_burst",
                    "action:refund_step_up",
                ],
                "score_delta": 30,
                "description": "Refund-abuse bridge score elevated — step-up / review",
            },
            {
                "id": "fd_case_karma_high",
                "when": [
                    {"field": "case_karma_high", "op": "is_true", "value": True},
                ],
                "tags": [
                    "vertical:food_delivery",
                    "risk:refund_burst",
                    "action:hard_challenge",
                ],
                "score_delta": 28,
                "description": "Case karma — elevated repeat refund / dispute loss rates",
            },
            {
                "id": "fd_promo_econ_high",
                "when": [
                    {"field": "promo_econ_high", "op": "is_true", "value": True},
                ],
                "tags": [
                    "vertical:food_delivery",
                    "risk:promo_farm",
                    "action:hard_challenge",
                ],
                "score_delta": 22,
                "description": "Promo economics depth engine elevated",
            },
            {
                "id": "fd_depth_fusion_high",
                "when": [
                    {"field": "depth_fusion_high", "op": "is_true", "value": True},
                ],
                "tags": [
                    "vertical:food_delivery",
                    "risk:depth_fusion",
                    "action:hard_challenge",
                ],
                "score_delta": 28,
                "description": "Multi-signal depth fusion elevated",
            },
        ],
        "tag_rules": [],
    },
    "e_hailing": {
        "name": "Vertical E-Hailing",
        "version": 1,
        "velocity_presets": "standard",
        "kill_criteria": {**_DEFAULT_KILL, "min_precision": 0.015, "min_recall": 0.02},
        "rules": [
            {
                "id": "eh_self_ride_same_device",
                "when": [
                    {"field": "cross_role_same_device", "op": "is_true", "value": True},
                ],
                "tags": [
                    "vertical:e_hailing",
                    "risk:collusion_shared_device",
                    "action:hard_challenge",
                ],
                "score_delta": 34,
                "description": "Same device on driver + rider roles — collusion challenge",
            },
            {
                "id": "eh_driver_rider_pair_velocity",
                "when": [
                    {"field": "pair_trip_count_24h", "op": "gte", "value": 6},
                    {"field": "account_age_days", "op": "lte", "value": 30},
                ],
                "tags": [
                    "vertical:e_hailing",
                    "risk:collusion_shared_device",
                    "action:hard_challenge",
                ],
                "score_delta": 28,
                "description": "Repeated driver–rider pair velocity on young accounts",
            },
            {
                "id": "eh_location_spoof",
                "when": [
                    {"field": "is_location_spoof", "op": "is_true", "value": True},
                ],
                "tags": [
                    "vertical:e_hailing",
                    "risk:courier_spoof",
                    "action:hard_challenge",
                ],
                "score_delta": 30,
                "description": "Vendor location spoof/tamper signal on trip",
            },
            {
                "id": "eh_incentive_farm",
                "when": [
                    {"field": "transaction_count_24h", "op": "gte", "value": 20},
                    {"field": "amount", "op": "lte", "value": 15},
                    {"field": "account_age_days", "op": "lte", "value": 14},
                ],
                "tags": ["vertical:e_hailing", "risk:promo_farm"],
                "score_delta": 24,
                "description": "Driver incentive / completion farm pattern",
            },
            {
                "id": "eh_driver_bonus_farm",
                "when": [
                    {"field": "driver_bonus_farm", "op": "is_true", "value": True},
                ],
                "tags": [
                    "vertical:e_hailing",
                    "risk:promo_farm",
                    "action:hard_challenge",
                ],
                "score_delta": 22,
                "description": "Host-reported driver bonus claim farm",
            },
            {
                "id": "eh_worker_auth_fail",
                "when": [
                    {"field": "worker_auth_failed", "op": "is_true", "value": True},
                ],
                "tags": [
                    "vertical:e_hailing",
                    "risk:account_rental",
                    "action:suspend_driving",
                ],
                "score_delta": 36,
                "description": "Face/liveness re-auth failed — account rental / suspend driving",
            },
            {
                "id": "eh_payout_hold_spoof",
                "when": [
                    {"field": "amount", "op": "gte", "value": 200},
                    {"field": "is_emulator", "op": "is_true", "value": True},
                ],
                "tags": [
                    "vertical:e_hailing",
                    "action:payout_hold",
                    "risk:courier_spoof",
                ],
                "score_delta": 30,
                "description": "Driver payout with emulator spoof — hold pending review",
            },
        ],
        "tag_rules": [],
    },
}

# Plan aliases → canonical pack ids
_PACK_ALIASES: dict[str, str] = {
    "marketplace_goods": "marketplace",
    "last_mile": "logistics",
    "goods_marketplace": "marketplace",
    "ride_hailing": "e_hailing",
    "ehailing": "e_hailing",
}

# Ops posture: checkpoints, connectors, host-actions (honesty-aware)
_PACK_POSTURE: dict[str, dict[str, Any]] = {
    "marketplace": {
        "business_type": "marketplace_goods",
        "priority": 1,
        "checkpoints": [
            "seller_onboard",
            "listing",
            "checkout",
            "payout",
            "refund",
            "dispute",
        ],
        "required_connectors": ["identity_kyb", "chargeback_alert", "device"],
        "optional_connectors": ["brand_protection", "sanctions"],
        "host_actions": [
            "action:payout_hold",
            "action:suspend_sales",
            "action:kyb_collect",
            "action:kyb_disclose",
            "action:refund_hold",
            "action:dispute_open",
            "action:listing_takedown",
        ],
        "honesty": "Brand crawl and LIVE device require connectors; no forged claims.",
    },
    "qcommerce": {
        "business_type": "qcommerce",
        "priority": 2,
        "checkpoints": ["checkout", "redeem", "cancel", "payout"],
        "required_connectors": ["device"],
        "optional_connectors": ["worker_auth"],
        "host_actions": ["action:payout_delay", "action:hard_challenge"],
        "honesty": "Promo farms via pack + loyalty-abuse bridge when configured.",
    },
    "food_delivery": {
        "business_type": "food_delivery",
        "priority": 2,
        "checkpoints": ["checkout", "redeem", "cancel", "refund", "payout", "delivery"],
        "required_connectors": ["device"],
        "optional_connectors": ["worker_auth", "chargeback_alert"],
        "host_actions": [
            "action:payout_hold",
            "action:hard_challenge",
            "action:refund_hold",
            "action:refund_step_up",
        ],
        "honesty": "Refund/cancel heads via sibling bridges when configured.",
    },
    "logistics": {
        "business_type": "last_mile",
        "priority": 3,
        "checkpoints": ["accept", "delivery", "cod", "payout", "refund"],
        "required_connectors": ["device"],
        "optional_connectors": ["worker_auth"],
        "host_actions": [
            "action:payout_hold",
            "action:refund_hold",
            "action:hard_challenge",
        ],
        "honesty": "FTID intake is Downstream warehouse; Tarka holds on mismatch features.",
    },
    "offline_payment": {
        "business_type": "cod_offline",
        "priority": 3,
        "checkpoints": ["checkout", "delivery", "refund"],
        "required_connectors": [],
        "optional_connectors": ["device"],
        "host_actions": [
            "action:payout_hold",
            "action:hard_challenge",
        ],
        "honesty": "COD fake-order + theft both scored; host supplies COD flags.",
    },
    "e_hailing": {
        "business_type": "e_hailing",
        "priority": 2,
        "checkpoints": ["trip_request", "trip_complete", "bonus_claim", "payout"],
        "required_connectors": ["device", "worker_auth"],
        "optional_connectors": [],
        "host_actions": [
            "action:hard_challenge",
            "action:suspend_driving",
            "action:payout_hold",
        ],
        "honesty": "Location spoof from vendor connector; same-device = challenge then suspend.",
    },
    "fintech": {
        "business_type": "fintech",
        "priority": 4,
        "checkpoints": ["transfer", "login"],
        "required_connectors": ["sanctions"],
        "optional_connectors": ["device"],
        "host_actions": [],
        "honesty": "Starter pack — not marketplace-primary.",
    },
    "ecommerce": {
        "business_type": "ecommerce",
        "priority": 4,
        "checkpoints": ["checkout"],
        "required_connectors": ["device"],
        "optional_connectors": [],
        "host_actions": [],
        "honesty": "Starter pack — prefer marketplace pack for multi-sided trust.",
    },
    "gaming": {
        "business_type": "gaming",
        "priority": 5,
        "checkpoints": ["session", "purchase"],
        "required_connectors": ["device"],
        "optional_connectors": [],
        "host_actions": [],
        "honesty": "Starter pack.",
    },
}


def resolve_pack_name(name: str) -> str:
    key = (name or "").strip().lower()
    return _PACK_ALIASES.get(key, key)


def list_vertical_packs() -> dict[str, dict[str, Any]]:
    return {
        k: {
            "name": v["name"],
            "rules": len(v.get("rules", [])),
            "version": v.get("version", 1),
            "has_kill_criteria": bool(v.get("kill_criteria")),
            "business_type": (_PACK_POSTURE.get(k) or {}).get("business_type"),
            "priority": (_PACK_POSTURE.get(k) or {}).get("priority"),
            "checkpoints": list((_PACK_POSTURE.get(k) or {}).get("checkpoints") or []),
            "required_connectors": list(
                (_PACK_POSTURE.get(k) or {}).get("required_connectors") or []
            ),
            "host_actions": list(
                (_PACK_POSTURE.get(k) or {}).get("host_actions") or []
            ),
        }
        for k, v in _PACKS.items()
    }


def load_vertical_pack_ops_posture(
    *,
    connector_families: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Ops surface: packs + connector readiness (fail-closed honesty)."""
    families = connector_families or {}
    packs_out: list[dict[str, Any]] = []
    for pid, meta in sorted(
        _PACK_POSTURE.items(), key=lambda kv: (kv[1].get("priority") or 99, kv[0])
    ):
        if pid not in _PACKS:
            continue
        req = list(meta.get("required_connectors") or [])
        blockers: list[str] = []
        for fam in req:
            posture = families.get(fam) if isinstance(families, dict) else None
            if not isinstance(posture, dict):
                blockers.append(f"connector_unresolved:{fam}")
            elif not posture.get("live_claim_allowed"):
                blockers.append(f"connector_not_live:{fam}")
        packs_out.append(
            {
                "pack_id": pid,
                "name": _PACKS[pid]["name"],
                "rule_count": len(_PACKS[pid].get("rules") or []),
                **{k: meta[k] for k in meta},
                "connector_blockers": blockers,
                "pack_ready": len(blockers) == 0,
            }
        )
    return {
        "schema_id": "tarka.vertical_pack_ops_posture/v1",
        "packs": packs_out,
        "aliases": dict(_PACK_ALIASES),
        "priority_note": "marketplace-first (best OSS marketplace fraud OS)",
        "honesty": (
            "pack_ready requires LIVE connectors for required_connectors; "
            "rules still installable for shadow/sim without LIVE."
        ),
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
    key = resolve_pack_name(name)
    pack = _PACKS.get(key)
    if not pack:
        return None
    vp_key = pack.get("velocity_presets")
    presets = _VELOCITY_PRESETS.get(str(vp_key), []) if vp_key else []
    posture = dict(_PACK_POSTURE.get(key) or {})
    return {
        "id": key,
        "name": pack["name"],
        "version": pack.get("version", 1),
        "velocity_presets": presets,
        "rules": [dict(r) for r in pack.get("rules", [])],
        "tag_rules": [dict(r) for r in pack.get("tag_rules", [])],
        "kill_criteria": dict(pack.get("kill_criteria") or _DEFAULT_KILL),
        "posture": posture,
    }
