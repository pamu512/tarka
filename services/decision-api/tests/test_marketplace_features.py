"""Marketplace feature wiring for KYB / FTID / chargeback / collusion."""

from decision_api.marketplace_features import apply_marketplace_features
from decision_api.simulation_api import _eval_with_override_rules
from decision_api.vertical_packs import get_vertical_pack


def test_apply_kyb_and_ftid_flags():
    feats: dict = {}
    apply_marketplace_features(
        feats,
        {"seller_gmv_30d": 8000, "kyb_state": "unverified"},
        {"ftid_intake_mismatch": True, "chargeback_early_alert": 1},
    )
    assert feats["seller_gmv_30d"] == 8000.0
    assert feats["kyb_unverified"] is True
    assert feats["ftid_intake_mismatch"] is True
    assert feats["chargeback_early_alert"] is True


def test_marketplace_pack_fires_on_kyb_features():
    pack = get_vertical_pack("marketplace")
    assert pack is not None
    out = _eval_with_override_rules(
        {
            "payload": {
                "seller_gmv_30d": 9000,
                "kyb_unverified": True,
                "amount": 10,
                "account_age_days": 100,
                "transaction_count_24h": 1,
            }
        },
        pack["rules"],
    )
    assert "mkt_kyb_unverified_high_gmv" in out["rule_hits"]
    assert out["score"] >= 40
