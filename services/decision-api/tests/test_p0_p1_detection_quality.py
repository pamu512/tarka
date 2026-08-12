"""P0/P1 detection-quality suites — adversarial, listing, graph, fusion gates, KYB rescreen."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from decision_api.depth_engines import (
    apply_all_depth_engines,
    merge_depth_into_score_and_tags,
)
from decision_api.depth_fusion import METHOD as FUSION_METHOD
from decision_api.depth_fusion import compute_depth_fusion
from decision_api.graph_hints_merge import merge_partner_hints_into_party_graph
from decision_api.kyb_rescreen import (
    apply_rescreen_result,
    is_due_for_rescreen,
    select_due_sellers,
)
from decision_api.listing_risk import compute_listing_risk
from decision_api.party_graph_contract import assess_party_graph_quality
from decision_api.typology import evaluate_typologies
from decision_api.vertical_calibration import (
    calibrate_vertical,
    load_all_vertical_calibration_posture,
)
from decision_api.vertical_promote_registry import evaluate_holdout_for_pack

_ADV = (
    Path(__file__).parent / "fixtures" / "verticals" / "depth_adversarial_golden.jsonl"
)


def _load_adv() -> list[dict]:
    rows = []
    for line in _ADV.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            rows.append(json.loads(line))
    return rows


def test_adversarial_corpus_no_false_confidence():
    rank = {"pass": 0, "warning": 1, "alert": 2}
    for row in _load_adv():
        cid = row["id"]
        feats = dict(row.get("features") or {})
        meta = dict(row.get("metadata") or {})
        ev = apply_all_depth_engines(feats, None, meta)
        expect = row.get("expect") or {}
        for k in expect.get("evidence_keys") or []:
            assert k in ev, f"{cid}: missing {k}"
        for f in expect.get("features_true") or []:
            assert feats.get(f) is True, f"{cid}: expected true {f}"
        for f in expect.get("features_false") or []:
            assert feats.get(f) is not True, (
                f"{cid}: false-positive {f}={feats.get(f)!r}"
            )
        tags: list[str] = []
        hits: list[str] = []
        merge_depth_into_score_and_tags(evidence=ev, all_new_tags=tags, rule_hits=hits)
        typ = {t["id"]: t for t in evaluate_typologies(hits, feats)}
        for tid, mx in (expect.get("typology_max_breach") or {}).items():
            got = str((typ.get(tid) or {}).get("breach_level") or "pass")
            assert rank[got] <= rank[mx], f"{cid}: {tid} {got} > {mx}"
        for tid, mn in (expect.get("typology_min_breach") or {}).items():
            got = str((typ.get(tid) or {}).get("breach_level") or "pass")
            assert rank[got] >= rank[mn], f"{cid}: {tid} {got} < {mn}"
        if "max_fusion_score" in expect:
            fusion = ev.get("depth_fusion") or {}
            score = float(fusion.get("score_0_100") or 0.0)
            assert score <= float(expect["max_fusion_score"]) + 1e-6, (
                f"{cid}: fusion score {score} > max {expect['max_fusion_score']}"
            )


def test_fusion_uses_gated_diminishing_method():
    assert FUSION_METHOD == "gated_cooccurrence_v2"
    evidence = {
        "lifecycle_risk": {"score_0_100": 55},
        "ring_score": {"score_0_100": 50, "cross_role_same_device": True},
        "ftid_intake_gate": {"score_0_100": 60, "refund_hold": True},
        "promo_economics": {"score_0_100": 50},
        "dispute_representment": {"risk_0_100": 70},
        "seller_trajectory": {"score_0_100": 50},
    }
    feats = {
        "lifecycle_risk_high": True,
        "ring_score_high": True,
        "cross_role_same_device": True,
        "ftid_refund_hold": True,
        "promo_econ_high": True,
        "representment_weak": True,
        "seller_trajectory_high": True,
    }
    r = compute_depth_fusion(evidence=evidence, features=feats)
    assert r is not None
    assert r.evidence()["double_count_control"] == "diminishing_returns_v1"
    # Stacked recipes must not saturate at old 70+ from raw sum
    assert r.score_0_100 <= 62.0
    # Ungated: engines active but required features missing → multi_engine or fewer recipes
    r2 = compute_depth_fusion(
        evidence={
            "lifecycle_risk": {"score_0_100": 55},
            "promo_economics": {"score_0_100": 50},
        },
        features={},  # no high flags → may still activate on soft floor
    )
    assert r2 is not None


def test_fusion_child_score_damped_when_fused():
    feats: dict = {"amount": 120}
    meta = {
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
            ],
        },
    }
    ev = apply_all_depth_engines(feats, None, meta)
    assert "depth_fusion" in ev
    tags: list[str] = []
    hits: list[str] = []
    delta = merge_depth_into_score_and_tags(
        evidence=ev, all_new_tags=tags, rule_hits=hits
    )
    assert delta <= 45.0
    assert "depth_fusion_engine" in hits


def test_listing_risk_live_commerce():
    r = compute_listing_risk(
        metadata={
            "listing_risk": {
                "live_stream": True,
                "seller_account_age_days": 2,
                "price_vs_category_median_ratio": 0.08,
                "brand_protection_hit": True,
                "image_count": 0,
            }
        }
    )
    assert r is not None
    codes = {f.code for f in r.factors}
    assert "live_stream_new_seller" in codes
    assert "brand_protection_hit" in codes
    assert "action:listing_takedown" in r.tags


def test_party_graph_quality_weak_vs_ready():
    weak = assess_party_graph_quality(
        metadata={"party_graph": {"nodes": [{"id": "a"}], "edges": []}}
    )
    assert weak is not None
    assert weak["production_ready"] is False
    ready = assess_party_graph_quality(
        metadata={
            "party_graph": {
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
                        "ts": "2026-08-11T10:00:00Z",
                    },
                    {
                        "src": "s1",
                        "dst": "d1",
                        "type": "USES_DEVICE",
                        "ts": "2026-08-11T10:01:00Z",
                    },
                ],
            }
        }
    )
    assert ready is not None
    assert ready["production_ready"] is True


def test_ocr_hints_merge_into_party_graph():
    meta = {
        "party_graph": {
            "nodes": [{"id": "b1", "role": "buyer"}, {"id": "s1", "role": "seller"}],
            "edges": [],
        },
        "partner_graph_hints": {
            "ocr_device_clusters": [
                {
                    "cluster_id": "c9",
                    "entity_ids": [
                        {"id": "b1", "role": "buyer"},
                        {"id": "s1", "role": "seller"},
                    ],
                }
            ]
        },
    }
    merged = merge_partner_hints_into_party_graph(meta)
    assert merged is not None
    edges = merged["party_graph"]["edges"]
    assert any(e.get("source") == "ocr_device_cluster" for e in edges)
    feats: dict = {}
    ev = apply_all_depth_engines(feats, None, meta)
    assert feats.get("cross_role_same_device") is True
    assert "ring_score" in ev


def test_kyb_rescreen_due_and_hit():
    old = (datetime.now(UTC) - timedelta(days=45)).isoformat()
    rec = {
        "tenant_id": "t1",
        "seller_id": "s1",
        "kyb_state": "verified",
        "last_rescreen_at": old,
        "seller_gmv_30d": 8000,
        "suspicious_reports": [{"report_id": "r1"}],
    }
    assert is_due_for_rescreen(rec, max_age_days=30) is True
    due = select_due_sellers([rec], max_age_days=30)
    assert len(due) == 1
    hit = apply_rescreen_result(rec, hit=True, vendor_status="sanctions_hit")
    assert hit["kyb_state"] == "suspended"
    assert hit.get("last_rescreen_at")


def test_holdout_realism_and_calibration_honesty():
    p = evaluate_holdout_for_pack("marketplace")
    assert p.get("promote_live_claim_allowed") is False
    assert "holdout_realism" in p
    assert p["holdout_realism"]["synthetic_only"] is True
    assert p["holdout_realism"]["near_miss_or_hard_negative_rows"] >= 5
    assert isinstance(p["holdout_realism"].get("fixture_reliability_bins"), list)
    assert int(p["holdout_realism"].get("fixture_ece_bin_count") or 0) >= 1
    cal = calibrate_vertical("marketplace")
    assert cal["live_calibration_claim_allowed"] is False
    assert cal["fixture_calibration_only"] is True
    assert isinstance(cal.get("reliability_bins"), list)
    assert len(cal["reliability_bins"]) >= 1
    body = load_all_vertical_calibration_posture()
    assert body["live_calibration_claim_allowed"] is False
    for v in body["verticals"]:
        assert "reliability_bins" in v
        assert v.get("live_calibration_claim_allowed") is False


def test_depth_ops_lists_listing_engine():
    from decision_api.depth_engines_ops import load_depth_engines_ops_posture

    body = load_depth_engines_ops_posture()
    assert body["engine_count"] == 8
    ids = {e["engine_id"] for e in body["engines"]}
    assert "listing_risk" in ids
    assert "depth_fusion" in ids
