"""Depth: order lifecycle sequence risk engine."""

from __future__ import annotations

from decision_api.lifecycle_risk import (
    apply_lifecycle_risk_features,
    compute_lifecycle_risk,
)


def _trail(*stages_ts_amt_role):
    events = []
    for item in stages_ts_amt_role:
        stage, ts = item[0], item[1]
        ev = {"stage": stage, "ts": ts}
        if len(item) > 2 and item[2] is not None:
            ev["amount"] = item[2]
        if len(item) > 3 and item[3]:
            ev["actor_role"] = item[3]
        if len(item) > 4 and item[4]:
            ev["actor_id"] = item[4]
        if len(item) > 5 and item[5]:
            ev["signals"] = item[5]
        events.append(ev)
    return {"lifecycle": {"events": events, "vertical_profile": "marketplace_goods"}}


def test_clean_path_low_score():
    meta = _trail(
        ("checkout", "2026-08-11T10:00:00+00:00", 40, "buyer", "b1"),
        ("paid", "2026-08-11T10:01:00+00:00", 40, "buyer", "b1"),
        ("shipped", "2026-08-11T14:00:00+00:00", None, "seller", "s1"),
        ("delivered", "2026-08-12T10:00:00+00:00", None, "courier", "c1"),
    )
    r = compute_lifecycle_risk(metadata=meta)
    assert r is not None
    assert r.score_0_100 < 40
    assert "refund_before_delivery" not in {f.code for f in r.factors}


def test_refund_before_delivery():
    meta = _trail(
        ("checkout", "2026-08-11T10:00:00+00:00", 50, "buyer", "b1"),
        ("paid", "2026-08-11T10:01:00+00:00", 50, "buyer", "b1"),
        ("refund_requested", "2026-08-11T10:05:00+00:00", 50, "buyer", "b1"),
    )
    r = compute_lifecycle_risk(metadata=meta)
    assert r is not None
    assert r.score_0_100 >= 25
    assert any(f.code == "refund_before_delivery" for f in r.factors)
    assert "action:refund_hold" in r.tags


def test_time_compression_food():
    meta = {
        "lifecycle": {
            "vertical_profile": "food_delivery",
            "events": [
                {"stage": "checkout", "ts": "2026-08-11T12:00:00Z", "amount": 20},
                {"stage": "paid", "ts": "2026-08-11T12:00:10Z", "amount": 20},
                {"stage": "delivered", "ts": "2026-08-11T12:00:40Z"},
            ],
        }
    }
    r = compute_lifecycle_risk(metadata=meta)
    assert r is not None
    assert any(f.code == "time_compression_delivery" for f in r.factors)


def test_cross_role_same_actor():
    meta = _trail(
        ("checkout", "2026-08-11T10:00:00+00:00", 30, "buyer", "same_user"),
        ("paid", "2026-08-11T10:01:00+00:00", 30, "buyer", "same_user"),
        ("shipped", "2026-08-11T11:00:00+00:00", None, "seller", "same_user"),
        ("delivered", "2026-08-12T11:00:00+00:00", None, "courier", "c1"),
    )
    r = compute_lifecycle_risk(metadata=meta)
    assert r is not None
    assert any(f.code == "cross_role_same_actor" for f in r.factors)
    assert "action:hard_challenge" in r.tags


def test_ftid_signal_on_refund_stage():
    meta = _trail(
        ("checkout", "2026-08-11T10:00:00+00:00", 80, "buyer", "b1"),
        ("paid", "2026-08-11T10:01:00+00:00", 80, "buyer", "b1"),
        ("delivered", "2026-08-12T10:00:00+00:00", None, "courier", "c1"),
        (
            "refund_requested",
            "2026-08-13T10:00:00+00:00",
            80,
            "buyer",
            "b1",
            {"intake_ok": False},
        ),
    )
    r = compute_lifecycle_risk(metadata=meta)
    assert r is not None
    assert any(f.code == "ftid_intake_mismatch" for f in r.factors)
    assert "risk:ftid" in r.tags


def test_refund_exceeds_paid():
    meta = _trail(
        ("paid", "2026-08-11T10:00:00+00:00", 40, "buyer", "b1"),
        ("delivered", "2026-08-12T10:00:00+00:00", None, "courier", "c1"),
        ("refund_requested", "2026-08-13T10:00:00+00:00", 90, "buyer", "b1"),
    )
    r = compute_lifecycle_risk(metadata=meta)
    assert r is not None
    assert any(f.code == "refund_exceeds_paid" for f in r.factors)


def test_apply_features():
    feats: dict = {}
    meta = _trail(
        ("checkout", "2026-08-11T10:00:00+00:00", 50, "buyer", "b1"),
        ("refund_requested", "2026-08-11T10:05:00+00:00", 50, "buyer", "b1"),
    )
    ev = apply_lifecycle_risk_features(feats, None, meta)
    assert ev is not None
    assert feats["lifecycle_risk_high"] is True
    assert feats.get("lifecycle_factor:refund_before_delivery") is True
    assert ev["method"] == "sequence_heuristic_v1"
    assert ev["schema_id"] == "tarka.lifecycle_risk/v1"


def test_missing_trail_returns_none():
    assert compute_lifecycle_risk(metadata={"order_id": "x"}) is None
    assert compute_lifecycle_risk(metadata={"lifecycle": {"events": []}}) is None


def test_food_cancel_after_pickup():
    meta = {
        "lifecycle": {
            "vertical_profile": "food_delivery",
            "events": [
                {"stage": "checkout", "ts": "2026-08-11T12:00:00Z", "amount": 22},
                {"stage": "paid", "ts": "2026-08-11T12:01:00Z", "amount": 22},
                {"stage": "accepted", "ts": "2026-08-11T12:05:00Z"},
                {"stage": "picked_up", "ts": "2026-08-11T12:20:00Z"},
                {"stage": "cancelled", "ts": "2026-08-11T12:22:00Z"},
            ],
        }
    }
    r = compute_lifecycle_risk(metadata=meta)
    assert r is not None
    codes = {f.code for f in r.factors}
    assert "cancel_after_pickup" in codes
    assert "action:hard_challenge" in r.tags


def test_food_rapid_cancel_refund():
    meta = {
        "lifecycle": {
            "vertical_profile": "food_delivery",
            "events": [
                {"stage": "checkout", "ts": "2026-08-11T12:00:00Z", "amount": 18},
                {"stage": "paid", "ts": "2026-08-11T12:01:00Z", "amount": 18},
                {"stage": "cancelled", "ts": "2026-08-11T12:04:00Z"},
                {
                    "stage": "refund_requested",
                    "ts": "2026-08-11T12:06:00Z",
                    "amount": 18,
                },
            ],
        }
    }
    r = compute_lifecycle_risk(metadata=meta)
    assert r is not None
    assert any(f.code == "rapid_cancel_refund" for f in r.factors)


def test_ehailing_cancel_storm_and_fast_cancel():
    meta = {
        "lifecycle": {
            "vertical_profile": "e_hailing",
            "events": [
                {"stage": "checkout", "ts": "2026-08-11T20:00:00Z", "amount": 15},
                {"stage": "paid", "ts": "2026-08-11T20:00:30Z", "amount": 15},
                {"stage": "accepted", "ts": "2026-08-11T20:01:00Z"},
                {"stage": "cancelled", "ts": "2026-08-11T20:01:30Z"},
                {"stage": "cancelled", "ts": "2026-08-11T20:02:00Z"},
            ],
        }
    }
    r = compute_lifecycle_risk(metadata=meta)
    assert r is not None
    codes = {f.code for f in r.factors}
    assert "cancel_storm" in codes
    assert "cancel_seconds_after_accept" in codes


def test_chargeback_without_delivery():
    meta = _trail(
        ("checkout", "2026-08-11T10:00:00+00:00", 60, "buyer", "b1"),
        ("paid", "2026-08-11T10:01:00+00:00", 60, "buyer", "b1"),
        ("chargeback", "2026-08-11T11:00:00+00:00", 60, "buyer", "b1"),
    )
    r = compute_lifecycle_risk(metadata=meta)
    assert r is not None
    assert any(f.code == "chargeback_without_delivery" for f in r.factors)
    assert "action:dispute_open" in r.tags


def test_last_mile_cod_refuse_signal():
    meta = {
        "lifecycle": {
            "vertical_profile": "last_mile",
            "events": [
                {"stage": "checkout", "ts": "2026-08-11T09:00:00Z", "amount": 70},
                {"stage": "paid", "ts": "2026-08-11T09:01:00Z", "amount": 70},
                {"stage": "accepted", "ts": "2026-08-11T09:10:00Z"},
                {
                    "stage": "out_for_delivery",
                    "ts": "2026-08-11T11:00:00Z",
                    "signals": {"cod_refused": True},
                },
            ],
        }
    }
    r = compute_lifecycle_risk(metadata=meta)
    assert r is not None
    assert any(f.code == "cod_refuse_on_stage" for f in r.factors)
    assert "risk:cod_abuse" in r.tags
