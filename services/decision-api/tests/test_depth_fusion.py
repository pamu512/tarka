"""Cross-engine depth fusion — multi-signal detection."""

from __future__ import annotations

from decision_api.depth_engines import apply_all_depth_engines, merge_depth_into_score_and_tags
from decision_api.depth_fusion import compute_depth_fusion
from decision_api.simulation_api import _eval_with_override_rules
from decision_api.typology import evaluate_typologies
from decision_api.vertical_packs import get_vertical_pack


def test_single_engine_no_fusion():
    feats: dict = {}
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
                    "ts": "2026-08-11T10:05:00Z",
                    "amount": 120,
                    "actor_role": "buyer",
                    "actor_id": "b1",
                },
            ]
        },
    }
    ev = apply_all_depth_engines(feats, None, meta)
    assert "lifecycle_risk" in ev
    assert "depth_fusion" not in ev
    assert feats.get("depth_fusion_high") is not True


def test_lifecycle_ring_fusion_detects_collusion_refund_farm():
    feats: dict = {"amount": 120}
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
                    "ts": "2026-08-11T10:08:00Z",
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
                {"id": "d1", "role": "device"},
            ],
            "edges": [
                {"src": "b1", "dst": "d1", "type": "USES_DEVICE"},
                {"src": "s1", "dst": "d1", "type": "USES_DEVICE"},
                {"src": "b1", "dst": "s1", "type": "TRANSACTED", "count_24h": 9},
            ],
        },
    }
    ev = apply_all_depth_engines(feats, None, meta)
    assert "depth_fusion" in ev
    fuse = ev["depth_fusion"]
    assert fuse["method"] == "gated_cooccurrence_v2"
    assert fuse["double_count_control"] == "diminishing_returns_v1"
    assert fuse["live_claim_allowed"] is False
    codes = {f["code"] for f in fuse["factors"]}
    assert "lifecycle_ring" in codes
    assert feats["depth_fusion_high"] is True
    assert feats["fusion_factor:lifecycle_ring"] is True
    assert "risk:collusion_refund_farm" in fuse["tags"]
    assert "action:hard_challenge" in fuse["tags"]

    tags: list[str] = []
    hits: list[str] = []
    delta = merge_depth_into_score_and_tags(
        evidence=ev, all_new_tags=tags, rule_hits=hits
    )
    assert "depth_fusion_engine" in hits
    assert delta > 0

    pack = get_vertical_pack("marketplace")
    out = _eval_with_override_rules({"payload": feats}, pack["rules"])
    assert "mkt_depth_fusion_high" in out["rule_hits"]

    typ = evaluate_typologies(hits + list(out["rule_hits"]), feats)
    fusion_typ = next(t for t in typ if t["id"] == "marketplace_depth_fusion")
    assert fusion_typ["breach_level"] in ("warning", "alert")


def test_lifecycle_ftid_fusion_recipe():
    evidence = {
        "lifecycle_risk": {"score_0_100": 55, "tags": []},
        "ftid_intake_gate": {"score_0_100": 60, "refund_hold": True, "tags": []},
    }
    feats = {"lifecycle_risk_high": True, "ftid_refund_hold": True}
    r = compute_depth_fusion(evidence=evidence, features=feats)
    assert r is not None
    assert any(f.code == "lifecycle_ftid" for f in r.factors)
    assert "action:refund_hold" in r.tags


def test_ftid_representment_and_promo_ftid_recipes():
    evidence = {
        "ftid_intake_gate": {"score_0_100": 60, "refund_hold": True, "tags": []},
        "dispute_representment": {"risk_0_100": 70, "tags": []},
        "promo_economics": {"score_0_100": 50, "tags": []},
    }
    feats = {
        "ftid_refund_hold": True,
        "representment_weak": True,
        "promo_econ_high": True,
    }
    r = compute_depth_fusion(evidence=evidence, features=feats)
    assert r is not None
    codes = {f.code for f in r.factors}
    assert "ftid_representment" in codes
    assert "promo_ftid" in codes
    assert "promo_representment" in codes
    assert "risk:friendly_fraud" in r.tags


def test_ring_ftid_and_lifecycle_promo_recipes():
    evidence = {
        "ring_score": {"score_0_100": 50, "cross_role_same_device": True, "tags": []},
        "ftid_intake_gate": {"score_0_100": 55, "refund_hold": True, "tags": []},
        "lifecycle_risk": {"score_0_100": 48, "tags": []},
        "promo_economics": {"score_0_100": 45, "tags": []},
    }
    feats = {
        "ring_score_high": True,
        "ftid_refund_hold": True,
        "lifecycle_risk_high": True,
        "promo_econ_high": True,
    }
    r = compute_depth_fusion(evidence=evidence, features=feats)
    assert r is not None
    codes = {f.code for f in r.factors}
    assert "ring_ftid" in codes
    assert "lifecycle_promo" in codes
    assert "lifecycle_ftid" in codes


def test_honest_path_no_fusion():
    feats: dict = {"amount": 50, "account_age_days": 400}
    meta = {
        "vertical_profile": "marketplace_goods",
        "lifecycle": {
            "events": [
                {
                    "stage": "checkout",
                    "ts": "2026-08-11T10:00:00Z",
                    "amount": 50,
                    "actor_role": "buyer",
                    "actor_id": "b2",
                },
                {
                    "stage": "paid",
                    "ts": "2026-08-11T10:02:00Z",
                    "amount": 50,
                    "actor_role": "buyer",
                    "actor_id": "b2",
                },
                {
                    "stage": "shipped",
                    "ts": "2026-08-11T14:00:00Z",
                    "amount": 50,
                    "actor_role": "seller",
                    "actor_id": "s2",
                },
                {
                    "stage": "delivered",
                    "ts": "2026-08-12T16:00:00Z",
                    "amount": 50,
                    "actor_role": "courier",
                    "actor_id": "c2",
                },
            ]
        },
        "party_graph": {
            "nodes": [
                {"id": "b2", "role": "buyer"},
                {"id": "s2", "role": "seller"},
            ],
            "edges": [
                {"src": "b2", "dst": "s2", "type": "TRANSACTED", "count_24h": 1},
            ],
        },
    }
    ev = apply_all_depth_engines(feats, None, meta)
    assert "depth_fusion" not in ev


def test_ops_lists_fusion_engine():
    from decision_api.depth_engines_ops import load_depth_engines_ops_posture

    body = load_depth_engines_ops_posture()
    assert body["engine_count"] == 8
    ids = {e["engine_id"] for e in body["engines"]}
    assert "depth_fusion" in ids
    assert "listing_risk" in ids
