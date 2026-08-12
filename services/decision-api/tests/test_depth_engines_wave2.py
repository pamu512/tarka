"""Depth wave 2: trajectory, FTID FSM, promo economics, representment."""

from __future__ import annotations

from decision_api.depth_engines import apply_all_depth_engines, merge_depth_into_score_and_tags
from decision_api.dispute_representment import compute_representment_strength
from decision_api.ftid_intake_gate import compute_ftid_gate
from decision_api.promo_economics import compute_promo_economics
from decision_api.seller_trajectory import compute_seller_trajectory
from decision_api.simulation_api import _eval_with_override_rules
from decision_api.vertical_packs import get_vertical_pack


def test_seller_trajectory_refund_changepoint():
    meta = {
        "seller_trajectory": {
            "seller_id": "s9",
            "windows": [
                {"gmv": 1000, "refund_rate": 0.05, "order_count": 40, "payout_amount": 800},
                {"gmv": 1200, "refund_rate": 0.06, "order_count": 45, "payout_amount": 900},
                {"gmv": 1100, "refund_rate": 0.28, "order_count": 20, "payout_amount": 2000},
                {"gmv": 900, "refund_rate": 0.40, "order_count": 10, "payout_amount": 2500},
            ],
        }
    }
    r = compute_seller_trajectory(metadata=meta)
    assert r is not None
    codes = {f.code for f in r.factors}
    assert "refund_rate_changepoint" in codes
    assert "action:payout_hold" in r.tags


def test_seller_trajectory_listing_burst():
    meta = {
        "seller_trajectory": {
            "seller_id": "s_list",
            "account_age_days": 120,
            "windows": [
                {"gmv": 400, "listing_count": 5, "payout_amount": 200, "order_count": 10},
                {"gmv": 450, "listing_count": 12, "payout_amount": 220, "order_count": 12},
                {"gmv": 500, "listing_count": 40, "payout_amount": 250, "order_count": 14},
            ],
        }
    }
    r = compute_seller_trajectory(metadata=meta)
    assert r is not None
    assert any(f.code == "listing_burst" for f in r.factors)
    assert "action:kyb_collect" in r.tags


def test_seller_trajectory_ato_then_payout():
    meta = {
        "seller_trajectory": {
            "seller_id": "s_ato",
            "signals": {
                "password_reset_hours_ago": 6,
                "new_payout_destination": True,
            },
            "windows": [
                {"gmv": 800, "payout_amount": 400, "order_count": 20, "refund_rate": 0.04},
                {"gmv": 820, "payout_amount": 450, "order_count": 22, "refund_rate": 0.05},
                {"gmv": 850, "payout_amount": 1600, "order_count": 18, "refund_rate": 0.06},
            ],
        }
    }
    r = compute_seller_trajectory(metadata=meta)
    assert r is not None
    codes = {f.code for f in r.factors}
    assert "ato_then_payout" in codes
    assert "risk:account_takeover" in r.tags
    assert "action:payout_hold" in r.tags


def test_seller_trajectory_listing_to_payout_burst():
    meta = {
        "seller_trajectory": {
            "seller_id": "s_dump",
            "account_age_days": 90,
            "windows": [
                {"gmv": 1000, "listing_count": 8, "payout_amount": 300, "order_count": 30},
                {"gmv": 1100, "listing_count": 15, "payout_amount": 400, "order_count": 32},
                {"gmv": 1200, "listing_count": 55, "payout_amount": 1800, "order_count": 28},
            ],
        }
    }
    r = compute_seller_trajectory(metadata=meta)
    assert r is not None
    codes = {f.code for f in r.factors}
    assert "listing_to_payout_burst" in codes
    assert "action:payout_hold" in r.tags


def test_ftid_missing_intake_holds():
    r = compute_ftid_gate(
        metadata={
            "ftid": {
                "carrier_delivered": True,
                "intake_received": False,
                "refund_requested": True,
                "hours_since_delivered": 96,
            }
        }
    )
    assert r is not None
    assert r.refund_hold is True
    assert r.mismatch_class == "missing_intake"
    assert "action:refund_hold" in r.tags


def test_ftid_empty_box():
    r = compute_ftid_gate(
        metadata={
            "ftid": {
                "carrier_delivered": True,
                "intake_received": True,
                "refund_requested": True,
                "intake_hash_ok": True,
                "weight_ok": True,
                "label_ok": True,
                "empty_box_suspected": True,
            }
        }
    )
    assert r is not None
    assert r.refund_hold is True
    assert r.mismatch_class == "empty_box"


def test_ftid_matched_releasable():
    r = compute_ftid_gate(
        metadata={
            "ftid": {
                "carrier_delivered": True,
                "intake_received": True,
                "refund_requested": True,
                "intake_hash_ok": True,
                "weight_ok": True,
                "label_ok": True,
                "empty_box_suspected": False,
            }
        }
    )
    assert r is not None
    assert r.refund_hold is False
    assert r.state == "refund_releasable"


def test_ftid_item_swap_and_serial_returner():
    r = compute_ftid_gate(
        metadata={
            "ftid": {
                "carrier_delivered": True,
                "intake_received": True,
                "refund_requested": True,
                "intake_hash_ok": False,
                "weight_ok": False,
                "label_ok": True,
                "prior_return_count_90d": 4,
                "hours_since_delivered": 3,
            }
        }
    )
    assert r is not None
    codes = {f.code for f in r.factors}
    assert "item_swap_suspected" in codes
    assert "multi_dimension_mismatch" in codes
    assert "serial_returner" in codes
    assert "instant_refund_after_delivery" in codes
    assert r.refund_hold is True
    assert "risk:friendly_fraud" in r.tags


def test_promo_stack_and_margin():
    r = compute_promo_economics(
        metadata={
            "promo_economics": {
                "list_price": 100,
                "paid_amount": 8,
                "discounts": [
                    {"type": "referral", "amount": 30},
                    {"type": "new_user", "amount": 30},
                    {"type": "partner", "amount": 32},
                ],
                "account_age_days": 1,
                "redeem_count_24h": 12,
                "friction_heads": {"multi_account": 0.8},
            }
        }
    )
    assert r is not None
    assert r.score_0_100 >= 40
    assert r.stack_depth == 3
    codes = {f.code for f in r.factors}
    assert "extreme_margin_erosion" in codes
    assert "incompatible_promo_stack" in codes


def test_promo_code_share_and_refund_loop():
    r = compute_promo_economics(
        metadata={
            "promo_economics": {
                "list_price": 80,
                "paid_amount": 20,
                "discounts": [{"type": "referral", "amount": 60}],
                "same_code_accounts_24h": 12,
                "device_redeem_accounts_24h": 5,
                "refund_after_promo": True,
                "first_order": True,
            }
        }
    )
    assert r is not None
    codes = {f.code for f in r.factors}
    assert "code_share_farm" in codes
    assert "device_cluster_redeem" in codes
    assert "refund_after_promo" in codes
    assert "first_order_max_discount" in codes
    assert "risk:promo_collusion" in r.tags


def test_representment_weak_missing_pod():
    r = compute_representment_strength(
        metadata={
            "dispute_evidence": {
                "reason_code": "4853",
                "has_pod": False,
                "has_tracking": False,
                "has_chat": False,
                "amount": 600,
                "hours_to_deadline": 12,
                "prior_won": 1,
                "prior_lost": 5,
            }
        }
    )
    assert r is not None
    assert r.risk_0_100 >= 45
    assert "pod" in r.missing
    assert "action:dispute_evidence_gap" in r.tags
    assert any(f.code == "serial_disputer" for f in r.factors)


def test_representment_early_alert_gap():
    r = compute_representment_strength(
        metadata={
            "dispute_evidence": {
                "reason_code": "4853",
                "has_pod": False,
                "has_tracking": False,
                "early_alert": True,
                "hours_since_alert": 60,
            }
        }
    )
    assert r is not None
    codes = {f.code for f in r.factors}
    assert "early_alert_no_fulfillment_evidence" in codes
    assert "stale_alert_incomplete_pack" in codes
    assert "risk:chargeback_alert_gap" in r.tags


def test_representment_strong_pack():
    r = compute_representment_strength(
        metadata={
            "dispute_evidence": {
                "reason_code": "4853",
                "has_pod": True,
                "has_tracking": True,
                "has_chat": True,
                "prior_won": 8,
                "prior_lost": 2,
            }
        }
    )
    assert r is not None
    assert r.strength_0_100 >= 80
    assert "dispute:strong_pack" in r.tags


def test_orchestrator_and_pack_consumers():
    meta = {
        "seller_trajectory": {
            "windows": [
                {"gmv": 500, "refund_rate": 0.04, "listing_count": 2, "account_age_days": 5},
                {"gmv": 800, "refund_rate": 0.05, "listing_count": 10, "account_age_days": 10},
                {"gmv": 2000, "refund_rate": 0.30, "listing_count": 40, "account_age_days": 14},
            ]
        },
        "ftid": {
            "carrier_delivered": True,
            "intake_received": False,
            "refund_requested": True,
        },
        "promo_economics": {
            "list_price": 50,
            "paid_amount": 5,
            "discounts": [{"type": "referral", "amount": 20}, {"type": "new_user", "amount": 25}],
            "redeem_count_24h": 10,
            "account_age_days": 2,
        },
        "dispute_evidence": {
            "reason_code": "4853",
            "has_pod": False,
            "has_tracking": True,
        },
    }
    feats: dict = {}
    evidence = apply_all_depth_engines(feats, None, meta)
    assert "seller_trajectory" in evidence
    assert "ftid_intake_gate" in evidence
    assert "promo_economics" in evidence
    assert "dispute_representment" in evidence
    assert feats.get("ftid_refund_hold") is True
    assert feats.get("promo_econ_high") is True
    assert feats.get("representment_weak") is True

    tags: list[str] = []
    hits: list[str] = []
    delta = merge_depth_into_score_and_tags(
        evidence=evidence, all_new_tags=tags, rule_hits=hits
    )
    assert delta > 0
    assert "ftid_intake_gate_engine" in hits

    pack = get_vertical_pack("marketplace")
    assert pack is not None
    out = _eval_with_override_rules({"payload": feats}, pack["rules"])
    assert "mkt_ftid_hold" in out["rule_hits"]
    assert "mkt_promo_econ_high" in out["rule_hits"]
    assert "mkt_representment_weak" in out["rule_hits"]
