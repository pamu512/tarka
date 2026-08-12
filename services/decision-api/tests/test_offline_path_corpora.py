"""Offline path (no tenants): graph library, scaled goldens, promote CI gates."""

from __future__ import annotations

import json
from pathlib import Path

from decision_api.depth_engines import apply_all_depth_engines, merge_depth_into_score_and_tags
from decision_api.party_graph_contract import assess_party_graph_quality
from decision_api.typology import evaluate_typologies
from decision_api.vertical_calibration import load_all_vertical_calibration_posture
from decision_api.vertical_promote_registry import (
    evaluate_holdout_for_pack,
    load_all_vertical_promote_posture,
)

_FIXTURES = Path(__file__).parent / "fixtures"
_GRAPHS = _FIXTURES / "graphs"
_VERT = _FIXTURES / "verticals"
_BREACH = {"pass": 0, "warning": 1, "alert": 2}


def _load_jsonl(path: Path) -> list[dict]:
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            rows.append(json.loads(line))
    return rows


def _run_expect(row: dict) -> None:
    cid = row.get("id") or "<missing>"
    feats = dict(row.get("features") or {})
    meta = dict(row.get("metadata") or {})
    if "party_graph" in row and "party_graph" not in meta:
        meta["party_graph"] = row["party_graph"]
    if row.get("metadata_extra"):
        meta.update(row["metadata_extra"])
    ev = apply_all_depth_engines(feats, None, meta)
    expect = row.get("expect") or {}
    for k in expect.get("evidence_keys") or []:
        assert k in ev, f"{cid}: missing evidence {k}"
    for f in expect.get("features_true") or []:
        assert feats.get(f) is True, f"{cid}: expected true {f} got {feats.get(f)!r}"
    for f in expect.get("features_false") or []:
        assert feats.get(f) is not True, f"{cid}: FP {f}={feats.get(f)!r}"
    # also allow expect keys as direct feature asserts (graph lib style)
    for k, v in expect.items():
        if k.startswith("features_") or k in ("evidence_keys", "typology_min_breach", "typology_max_breach"):
            continue
        if k == "production_ready":
            gq = ev.get("party_graph_quality") or assess_party_graph_quality(metadata=meta)
            assert gq is not None
            assert gq["production_ready"] is v, f"{cid}: production_ready"
            continue
        if k == "cross_role_same_device":
            assert bool(feats.get("cross_role_same_device")) is bool(v), f"{cid}: cross_role"
            continue
        if k in ("max_fusion_score",):
            continue
        if k.startswith("ring_factor:") or k.endswith("_high"):
            assert bool(feats.get(k)) is bool(v), f"{cid}: {k}"
    tags: list[str] = []
    hits: list[str] = []
    merge_depth_into_score_and_tags(evidence=ev, all_new_tags=tags, rule_hits=hits)
    typ = {t["id"]: t for t in evaluate_typologies(hits, feats)}
    for tid, mn in (expect.get("typology_min_breach") or {}).items():
        got = str((typ.get(tid) or {}).get("breach_level") or "pass")
        assert _BREACH[got] >= _BREACH[mn], f"{cid}: {tid} {got}<{mn}"
    for tid, mx in (expect.get("typology_max_breach") or {}).items():
        got = str((typ.get(tid) or {}).get("breach_level") or "pass")
        assert _BREACH[got] <= _BREACH[mx], f"{cid}: {tid} {got}>{mx}"
    if "max_fusion_score" in expect:
        fusion = ev.get("depth_fusion") or {}
        score = float(fusion.get("score_0_100") or 0.0)
        assert score <= float(expect["max_fusion_score"]) + 1e-6, (
            f"{cid}: fusion score {score} > max {expect['max_fusion_score']}"
        )


def test_party_graph_fixture_library():
    catalog = json.loads((_GRAPHS / "catalog.json").read_text(encoding="utf-8"))
    assert catalog["schema_id"] == "tarka.party_graph_fixture_lib/v1"
    assert len(catalog["graphs"]) >= 16
    classes = {g["class"] for g in catalog["graphs"]}
    assert {"collusion", "honest", "noisy"} <= classes
    noisy = [g for g in catalog["graphs"] if g["class"] == "noisy"]
    assert len(noisy) >= 6
    for entry in catalog["graphs"]:
        path = _GRAPHS / f"{entry['id']}.json"
        assert path.is_file(), path
        row = json.loads(path.read_text(encoding="utf-8"))
        row["expect"] = entry["expect"]
        _run_expect(row)


def test_adversarial_corpus_min_size():
    rows = _load_jsonl(_VERT / "depth_adversarial_golden.jsonl")
    assert len(rows) >= 30
    diffs = {r.get("difficulty") for r in rows}
    assert "adversarial" in diffs
    assert "near_miss" in diffs
    fusion_traps = [r for r in rows if "fusion-trap" in str(r.get("id") or "")]
    assert len(fusion_traps) >= 2
    for row in rows:
        _run_expect(row)


def test_listing_scale_golden():
    rows = _load_jsonl(_VERT / "marketplace_listing_golden.jsonl")
    assert len(rows) >= 50
    abuse = [r for r in rows if r.get("difficulty") == "abuse"]
    honest = [r for r in rows if r.get("difficulty") == "honest"]
    near = [r for r in rows if r.get("difficulty") == "near_miss"]
    assert len(abuse) >= 20
    assert len(honest) >= 15
    assert len(near) >= 8
    for row in rows:
        _run_expect(row)


def test_e_hailing_scale_golden():
    rows = _load_jsonl(_VERT / "e_hailing_scale_golden.jsonl")
    assert len(rows) >= 70
    near = [r for r in rows if r.get("difficulty") == "near_miss"]
    assert len(near) >= 15
    for row in rows:
        _run_expect(row)


def test_promote_requires_near_miss_and_blocks_critical_ece():
    body = load_all_vertical_promote_posture()
    assert body["promote_live_claim_allowed"] is False
    for pack in body["packs"]:
        realism = pack.get("holdout_realism") or {}
        assert realism.get("synthetic_only") is True
        assert realism.get("near_miss_or_hard_negative_rows", 0) >= 5
        assert realism.get("near_miss_ratio", 0) >= 0.05
        assert "holdout_near_miss_below_min" not in str(pack.get("blockers") or [])
        assert pack["promote_fixture_claim_allowed"] is True


def test_calibration_ops_fixture_only_gate_surface():
    body = load_all_vertical_calibration_posture()
    assert body["live_calibration_claim_allowed"] is False
    assert body["fixture_calibration_only"] is True
    for v in body["verticals"]:
        assert v.get("drift_flag") != "critical"
        bins = v.get("reliability_bins") or []
        assert isinstance(bins, list)
        assert len(bins) >= 1


def test_promote_blocked_without_near_miss_rows():
    from unittest.mock import patch

    # All rows lack difficulty tags → near_miss=0 → blocker
    rows = [
        {"id": f"x{i}", "y": i % 2, "features": {"amount": 10, "account_age_days": 400}}
        for i in range(40)
    ]
    # sprinkle positives that pack might hit
    for i in range(20):
        rows.append(
            {
                "id": f"p{i}",
                "y": 1,
                "features": {
                    "cross_role_same_device": True,
                    "lifecycle_risk_high": True,
                    "ftid_refund_hold": True,
                    "seller_gmv_30d": 50000,
                    "kyb_unverified": True,
                    "amount": 200,
                    "account_age_days": 2,
                },
            }
        )
    with patch(
        "decision_api.vertical_promote_registry.load_holdout_rows",
        return_value=rows,
    ):
        result = evaluate_holdout_for_pack("marketplace")
    assert result["promote_fixture_claim_allowed"] is False
    assert any("near_miss" in b for b in result.get("blockers") or [])
