"""Food delivery golden — promo farm, bridges heads, karma, honest allow."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from decision_api.case_karma_features import apply_case_karma_from_sources
from decision_api.depth_engines import apply_all_depth_engines
from decision_api.friendly_fraud_features import apply_friendly_fraud_features
from decision_api.marketplace_features import apply_marketplace_features
from decision_api.simulation_api import _eval_with_override_rules
from decision_api.vertical_packs import get_vertical_pack

_GOLDEN = Path(__file__).parent / "fixtures" / "verticals" / "food_promo_farm_golden.jsonl"


def _rows() -> list[dict]:
    return [
        json.loads(line)
        for line in _GOLDEN.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def test_food_golden_count():
    assert len(_rows()) >= 8


@pytest.mark.parametrize("row", _rows(), ids=lambda r: r["id"])
def test_food_golden_case(row: dict):
    pack = get_vertical_pack("food_delivery")
    assert pack is not None
    feats = dict(row.get("features") or {})
    meta = dict(row.get("metadata") or {"vertical_profile": "food_delivery"})
    apply_marketplace_features(feats, feats, meta)
    apply_friendly_fraud_features(feats, meta, feats)
    karma = meta.get("case_karma") if isinstance(meta.get("case_karma"), dict) else {}
    apply_case_karma_from_sources(feats, karma, meta)

    if row.get("run_depth"):
        apply_all_depth_engines(feats, None, meta)

    for f in row.get("expect_features_true") or []:
        assert feats.get(f) is True, f"{row['id']}: {f}={feats.get(f)!r}"

    out = _eval_with_override_rules({"payload": feats}, pack["rules"])
    hits = set(out["rule_hits"])
    tags = set(out.get("tags") or [])

    for h in row.get("expect_rule_hits") or []:
        assert h in hits, f"{row['id']}: missing {h} in {hits}"
    for h in row.get("expect_rule_hits_none_of") or []:
        assert h not in hits, f"{row['id']}: unexpected {h}"
    for t in row.get("expect_tags") or []:
        assert t in tags, f"{row['id']}: missing tag {t}"
    if row.get("expect_decision"):
        assert out["decision"] == row["expect_decision"]
    if row.get("expect_decision_not"):
        assert out["decision"] != row["expect_decision_not"]
    if row.get("expect_min_score") is not None:
        assert out["score"] >= float(row["expect_min_score"])
