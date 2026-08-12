"""Depth: multi-party ring score engine."""

from __future__ import annotations

from decision_api.ring_score import apply_ring_score_features, compute_ring_score


def test_honest_disjoint_low():
    meta = {
        "party_graph": {
            "nodes": [
                {"id": "b1", "role": "buyer"},
                {"id": "s1", "role": "seller"},
                {"id": "d_b", "role": "device"},
                {"id": "d_s", "role": "device"},
            ],
            "edges": [
                {"src": "b1", "dst": "d_b", "type": "USES_DEVICE"},
                {"src": "s1", "dst": "d_s", "type": "USES_DEVICE"},
            ],
        }
    }
    # Two components of size 2 — no cross-role on same device
    r = compute_ring_score(metadata=meta)
    assert r is not None
    assert r.cross_role_same_device is False
    assert r.score_0_100 < 40


def test_cross_role_same_device():
    meta = {
        "party_graph": {
            "nodes": [
                {"id": "b1", "role": "buyer"},
                {"id": "s1", "role": "seller"},
                {"id": "dev1", "role": "device"},
            ],
            "edges": [
                {"src": "b1", "dst": "dev1", "type": "USES_DEVICE"},
                {"src": "s1", "dst": "dev1", "type": "USES_DEVICE"},
            ],
        }
    }
    r = compute_ring_score(metadata=meta)
    assert r is not None
    assert r.cross_role_same_device is True
    assert r.score_0_100 >= 30
    assert any(f.code == "cross_role_device" for f in r.factors)
    assert "action:hard_challenge" in r.tags
    assert r.evidence()["gnn_claim_allowed"] is False
    assert r.evidence()["method"] == "heuristic_v1"


def test_driver_rider_collusion_device():
    meta = {
        "party_graph": {
            "nodes": [
                {"id": "drv", "role": "driver"},
                {"id": "rid", "role": "rider"},
                {"id": "phone", "role": "device"},
            ],
            "edges": [
                {"src": "drv", "dst": "phone", "type": "USES_DEVICE"},
                {"src": "rid", "dst": "phone", "type": "USES_DEVICE"},
                {
                    "src": "drv",
                    "dst": "rid",
                    "type": "TRIPPED",
                    "count_24h": 12,
                },
            ],
        }
    }
    r = compute_ring_score(metadata=meta)
    assert r is not None
    assert r.cross_role_same_device is True
    assert any(f.code == "pair_velocity" for f in r.factors)


def test_promo_hub():
    nodes = [{"id": "promo1", "role": "promo"}] + [
        {"id": f"b{i}", "role": "buyer"} for i in range(6)
    ]
    edges = [{"src": "promo1", "dst": f"b{i}", "type": "REDEEMED"} for i in range(6)]
    r = compute_ring_score(metadata={"party_graph": {"nodes": nodes, "edges": edges}})
    assert r is not None
    assert any(f.code == "promo_hub" for f in r.factors)
    assert "risk:promo_farm" in r.tags


def test_cross_role_payment_instrument():
    meta = {
        "party_graph": {
            "nodes": [
                {"id": "b1", "role": "buyer"},
                {"id": "s1", "role": "seller"},
                {"id": "card1", "role": "payment_instrument"},
            ],
            "edges": [
                {"src": "b1", "dst": "card1", "type": "USES_PAYMENT"},
                {"src": "s1", "dst": "card1", "type": "USES_PAYMENT"},
            ],
        }
    }
    r = compute_ring_score(metadata=meta)
    assert r is not None
    assert r.cross_role_same_device is True
    assert any(f.code == "cross_role_payment" for f in r.factors)
    assert "risk:shared_payment_instrument" in r.tags


def test_place_hub():
    nodes = [{"id": "plc1", "role": "place"}] + [
        {"id": f"u{i}", "role": "buyer" if i % 2 == 0 else "seller"} for i in range(5)
    ]
    edges = [{"src": "plc1", "dst": f"u{i}", "type": "SEEN_AT"} for i in range(5)]
    r = compute_ring_score(metadata={"party_graph": {"nodes": nodes, "edges": edges}})
    assert r is not None
    codes = {f.code for f in r.factors}
    assert "place_hub" in codes
    assert "risk:place_hub" in r.tags


def test_promo_device_role_chain():
    meta = {
        "party_graph": {
            "nodes": [
                {"id": "promo1", "role": "promo"},
                {"id": "dev1", "role": "device"},
                {"id": "b1", "role": "buyer"},
                {"id": "s1", "role": "seller"},
            ],
            "edges": [
                {"src": "promo1", "dst": "dev1", "type": "REDEEMED_ON"},
                {"src": "b1", "dst": "dev1", "type": "USES_DEVICE"},
                {"src": "s1", "dst": "dev1", "type": "USES_DEVICE"},
            ],
        }
    }
    r = compute_ring_score(metadata=meta)
    assert r is not None
    assert any(f.code == "promo_device_role_chain" for f in r.factors)
    assert "risk:promo_farm" in r.tags


def test_temporal_fresh_burst_and_stale_decay():
    # Fresh burst: many edges with recent ts
    as_of = "2026-08-11T12:00:00Z"
    fresh = {
        "party_graph": {
            "as_of": as_of,
            "nodes": [
                {"id": "b1", "role": "buyer"},
                {"id": "s1", "role": "seller"},
                {"id": "d1", "role": "device"},
            ],
            "edges": [
                {
                    "src": "b1",
                    "dst": "d1",
                    "type": "USES_DEVICE",
                    "ts": "2026-08-11T11:30:00Z",
                },
                {
                    "src": "s1",
                    "dst": "d1",
                    "type": "USES_DEVICE",
                    "ts": "2026-08-11T11:40:00Z",
                },
                {
                    "src": "b1",
                    "dst": "s1",
                    "type": "TRANSACTED",
                    "count_24h": 8,
                    "ts": "2026-08-11T11:50:00Z",
                },
            ],
        }
    }
    r = compute_ring_score(metadata=fresh)
    assert r is not None
    assert any(f.code == "fresh_edge_burst" for f in r.factors)

    # Stale velocity decay: pair edges old → lower pair_velocity weight
    stale = {
        "party_graph": {
            "as_of": as_of,
            "nodes": [
                {"id": "b1", "role": "buyer"},
                {"id": "s1", "role": "seller"},
                {"id": "d1", "role": "device"},
            ],
            "edges": [
                {
                    "src": "b1",
                    "dst": "d1",
                    "type": "USES_DEVICE",
                    "age_hours": 100,
                },
                {
                    "src": "s1",
                    "dst": "d1",
                    "type": "USES_DEVICE",
                    "age_hours": 100,
                },
                {
                    "src": "b1",
                    "dst": "s1",
                    "type": "TRANSACTED",
                    "count_24h": 12,
                    "age_hours": 100,
                },
            ],
        }
    }
    r2 = compute_ring_score(metadata=stale)
    assert r2 is not None
    assert any(f.code == "stale_edge_dominance" for f in r2.factors)
    pv = next(f for f in r2.factors if f.code == "pair_velocity")
    assert pv.weight < 22.0  # decayed from full 22


def test_worker_auth_attr():
    meta = {
        "party_graph": {
            "nodes": [
                {
                    "id": "drv",
                    "role": "driver",
                    "attrs": {"worker_auth_failed": True},
                },
                {"id": "rid", "role": "rider"},
                {"id": "d1", "role": "device"},
            ],
            "edges": [
                {"src": "drv", "dst": "d1", "type": "USES_DEVICE"},
                {"src": "rid", "dst": "d1", "type": "USES_DEVICE"},
            ],
        }
    }
    r = compute_ring_score(metadata=meta)
    assert r is not None
    assert any(f.code == "worker_auth_failed" for f in r.factors)
    assert "action:suspend_driving" in r.tags


def test_apply_features_sets_cross_role():
    feats: dict = {}
    meta = {
        "party_graph": {
            "nodes": [
                {"id": "b1", "role": "buyer"},
                {"id": "c1", "role": "courier"},
                {"id": "d1", "role": "device"},
            ],
            "edges": [
                {"src": "b1", "dst": "d1", "type": "USES_DEVICE"},
                {"src": "c1", "dst": "d1", "type": "USES_DEVICE"},
            ],
        }
    }
    ev = apply_ring_score_features(feats, None, meta)
    assert ev is not None
    assert feats["cross_role_same_device"] is True
    assert feats["ring_score_high"] is True
    assert feats.get("ring_factor:cross_role_device") is True


def test_missing_graph_none():
    assert compute_ring_score(metadata={}) is None
