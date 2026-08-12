"""E-hailing golden suite — pack rules, depth, typologies, escalation (no LIVE)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from decision_api.depth_engines import (
    apply_all_depth_engines,
    merge_depth_into_score_and_tags,
)
from decision_api.ehailing_escalation import (
    apply_ehailing_challenge_escalation,
    ehailing_challenge_store,
)
from decision_api.marketplace_features import apply_marketplace_features
from decision_api.simulation_api import _eval_with_override_rules
from decision_api.typology import evaluate_typologies
from decision_api.vertical_packs import get_vertical_pack

_GOLDEN = Path(__file__).parent / "fixtures" / "verticals" / "e_hailing_golden.jsonl"
_BREACH_RANK = {"pass": 0, "warning": 1, "alert": 2}


def _rows() -> list[dict]:
    out = []
    for line in _GOLDEN.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            out.append(json.loads(line))
    return out


def test_e_hailing_golden_count():
    assert len(_rows()) >= 8


@pytest.mark.parametrize("row", _rows(), ids=lambda r: r["id"])
def test_e_hailing_golden_case(row: dict):
    pack = get_vertical_pack("e_hailing")
    assert pack is not None
    feats = dict(row.get("features") or {})
    meta = dict(row.get("metadata") or {"vertical_profile": "e_hailing"})
    apply_marketplace_features(feats, feats, meta)

    depth_hits: list[str] = []
    if row.get("run_depth"):
        evidence = apply_all_depth_engines(feats, None, meta)
        tags_acc: list[str] = []
        merge_depth_into_score_and_tags(
            evidence=evidence, all_new_tags=tags_acc, rule_hits=depth_hits
        )
        for f in row.get("expect_features_true") or []:
            assert feats.get(f) is True, f"{row['id']}: feature {f}"

    out = _eval_with_override_rules({"payload": feats}, pack["rules"])
    hits = set(out["rule_hits"]) | set(depth_hits)
    tags = set(out.get("tags") or [])

    for h in row.get("expect_rule_hits") or []:
        assert h in hits, f"{row['id']}: missing rule {h} in {hits}"
    for h in row.get("after_depth_expect_rule_hits") or []:
        assert h in hits, f"{row['id']}: after depth missing rule {h}"
    for h in row.get("expect_rule_hits_none_of") or []:
        assert h not in hits, f"{row['id']}: unexpected rule {h}"
    for t in row.get("expect_tags") or []:
        assert t in tags, f"{row['id']}: missing tag {t}"

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


@pytest.mark.asyncio
async def test_ehailing_challenge_escalates_to_suspend():
    ehailing_challenge_store.clear_memory_for_tests()
    tags = ["action:hard_challenge", "vertical:e_hailing"]
    hits: list[str] = ["eh_self_ride_same_device"]
    feats: dict = {}
    meta = {
        "vertical_profile": "e_hailing",
        "driver_id": "drv-esc-1",
        "ehailing_challenge_threshold": 3,
    }

    for i in range(1, 3):
        ev = await apply_ehailing_challenge_escalation(
            tenant_id="t1",
            entity_id="drv-esc-1",
            features=feats,
            payload=None,
            metadata=meta,
            tags=list(tags),
            rule_hits=list(hits),
        )
        assert ev is not None
        assert ev["escalated"] is False
        assert feats["eh_challenge_count"] == i

    tags2 = list(tags)
    hits2 = list(hits)
    ev = await apply_ehailing_challenge_escalation(
        tenant_id="t1",
        entity_id="drv-esc-1",
        features=feats,
        payload=None,
        metadata=meta,
        tags=tags2,
        rule_hits=hits2,
    )
    assert ev is not None and ev["escalated"] is True
    assert "action:suspend_driving" in tags2
    assert "eh_challenge_escalate_suspend" in hits2
    assert feats["eh_escalate_suspend_driving"] is True
