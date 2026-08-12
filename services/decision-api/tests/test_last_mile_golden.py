"""Last-mile FTID / POD / COD golden suite (host fields only, no carrier LIVE)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from decision_api.depth_engines import (
    apply_all_depth_engines,
    merge_depth_into_score_and_tags,
)
from decision_api.friendly_fraud_features import apply_friendly_fraud_features
from decision_api.marketplace_features import apply_marketplace_features
from decision_api.offline_payment_features import apply_offline_payment_features
from decision_api.simulation_api import _eval_with_override_rules
from decision_api.typology import evaluate_typologies
from decision_api.vertical_packs import get_vertical_pack

_GOLDEN = (
    Path(__file__).parent / "fixtures" / "verticals" / "last_mile_ftid_golden.jsonl"
)
_BREACH_RANK = {"pass": 0, "warning": 1, "alert": 2}


def _rows() -> list[dict]:
    return [
        json.loads(line)
        for line in _GOLDEN.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def test_last_mile_golden_count():
    assert len(_rows()) >= 8


@pytest.mark.parametrize("row", _rows(), ids=lambda r: r["id"])
def test_last_mile_golden_case(row: dict):
    pack_id = str(row.get("pack") or "logistics")
    pack = get_vertical_pack(pack_id)
    assert pack is not None, pack_id
    feats = dict(row.get("features") or {})
    meta = dict(row.get("metadata") or {})
    apply_offline_payment_features(feats, feats, meta)
    apply_friendly_fraud_features(feats, meta, feats)
    if row.get("apply_marketplace"):
        apply_marketplace_features(feats, feats, meta)

    depth_hits: list[str] = []
    if row.get("run_depth"):
        evidence = apply_all_depth_engines(feats, None, meta)
        tags_acc: list[str] = []
        merge_depth_into_score_and_tags(
            evidence=evidence, all_new_tags=tags_acc, rule_hits=depth_hits
        )

    for f in row.get("expect_features_true") or []:
        assert feats.get(f) is True, (
            f"{row['id']}: expected {f}=True got {feats.get(f)!r}"
        )
    for f in row.get("expect_features_false") or []:
        assert feats.get(f) is not True, f"{row['id']}: expected {f} not true"

    out = _eval_with_override_rules({"payload": feats}, pack["rules"])
    hits = set(out["rule_hits"]) | set(depth_hits)
    tags = set(out.get("tags") or [])

    for h in row.get("expect_rule_hits") or []:
        assert h in hits, f"{row['id']}: missing rule {h} in {hits}"
    for h in row.get("expect_rule_hits_none_of") or []:
        assert h not in hits, f"{row['id']}: unexpected {h}"
    for t in row.get("expect_tags") or []:
        assert t in tags, f"{row['id']}: missing tag {t} in {tags}"

    typ = evaluate_typologies(list(hits), feats)
    by_id = {t["id"]: t for t in typ}
    for tid, min_level in (row.get("typology_min_breach") or {}).items():
        assert tid in by_id, f"{row['id']}: missing typology {tid}"
        got = by_id[tid]["breach_level"]
        assert _BREACH_RANK[got] >= _BREACH_RANK[min_level], (
            f"{row['id']}: {tid} {got} < {min_level}"
        )
    for tid, max_level in (row.get("typology_max_breach") or {}).items():
        assert tid in by_id
        got = by_id[tid]["breach_level"]
        assert _BREACH_RANK[got] <= _BREACH_RANK[max_level]


def test_pod_features_from_flat_metadata():
    feats: dict = {}
    apply_friendly_fraud_features(
        feats, {"pod_otp_fail": True, "pod_geofence_miss": True}, None
    )
    assert feats["pod_otp_fail"] is True
    assert feats["pod_geofence_miss"] is True
    assert feats["pod_integrity_fail"] is True


def test_cod_refusal_and_jig_thresholds():
    feats: dict = {}
    apply_offline_payment_features(
        feats,
        None,
        {"is_cod": True, "cod_refusal_rate_30d": 0.4, "address_jig_count_7d": 4},
    )
    assert feats["cod_refusal_high"] is True
    assert feats["address_jig_high"] is True
