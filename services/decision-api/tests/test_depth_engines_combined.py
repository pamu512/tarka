"""Combined lifecycle + ring depth: stacked abuse on one evaluate feature pass."""

from __future__ import annotations

from decision_api.lifecycle_risk import apply_lifecycle_risk_features
from decision_api.ring_score import apply_ring_score_features
from decision_api.simulation_api import _eval_with_override_rules
from decision_api.vertical_packs import get_vertical_pack


def test_stacked_marketplace_abuse_features_and_pack():
    meta = {
        "vertical_profile": "marketplace_goods",
        "lifecycle": {
            "events": [
                {
                    "stage": "checkout",
                    "ts": "2026-08-11T10:00:00Z",
                    "amount": 120,
                    "actor_role": "buyer",
                    "actor_id": "b1",
                },
                {
                    "stage": "paid",
                    "ts": "2026-08-11T10:01:00Z",
                    "amount": 120,
                    "actor_role": "buyer",
                    "actor_id": "b1",
                },
                {
                    "stage": "refund_requested",
                    "ts": "2026-08-11T10:10:00Z",
                    "amount": 120,
                    "actor_role": "buyer",
                    "actor_id": "b1",
                    "signals": {"intake_ok": False},
                },
            ]
        },
        "party_graph": {
            "nodes": [
                {"id": "b1", "role": "buyer"},
                {"id": "s1", "role": "seller"},
                {"id": "shared_phone", "role": "device"},
            ],
            "edges": [
                {"src": "b1", "dst": "shared_phone", "type": "USES_DEVICE"},
                {"src": "s1", "dst": "shared_phone", "type": "USES_DEVICE"},
                {
                    "src": "b1",
                    "dst": "s1",
                    "type": "TRANSACTED",
                    "count_24h": 9,
                },
            ],
        },
    }
    feats: dict = {
        "amount": 120,
        "account_age_days": 3,
        "transaction_count_24h": 9,
    }
    life = apply_lifecycle_risk_features(feats, None, meta)
    ring = apply_ring_score_features(feats, None, meta)
    assert life is not None and ring is not None
    assert feats["lifecycle_risk_high"] is True
    assert feats["ring_score_high"] is True
    assert feats["cross_role_same_device"] is True
    assert "action:refund_hold" in life["tags"]
    assert "action:hard_challenge" in ring["tags"]

    pack = get_vertical_pack("marketplace")
    assert pack is not None
    out = _eval_with_override_rules({"payload": feats}, pack["rules"])
    hits = set(out["rule_hits"])
    assert "mkt_lifecycle_risk_high" in hits
    assert "mkt_ring_score_high" in hits
