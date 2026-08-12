"""Golden JSONL corpora for depth engines + typology factor bindings (no LIVE)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from decision_api.depth_engines import (
    apply_all_depth_engines,
    merge_depth_into_score_and_tags,
)
from decision_api.typology import evaluate_typologies

_FIXTURES = Path(__file__).parent / "fixtures" / "verticals"
_CORPORA = (
    "marketplace_depth_golden.jsonl",
    "food_depth_golden.jsonl",
    "last_mile_depth_golden.jsonl",
    "e_hailing_depth_golden.jsonl",
)

_BREACH_RANK = {"pass": 0, "warning": 1, "alert": 2}


def _load_rows(name: str) -> list[dict]:
    path = _FIXTURES / name
    assert path.is_file(), f"missing golden corpus: {path}"
    rows = []
    for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError as e:
            raise AssertionError(f"{name}:{i}: invalid JSON: {e}") from e
    assert rows, f"empty corpus: {name}"
    return rows


def _run_case(row: dict) -> None:
    cid = row.get("id") or "<missing-id>"
    meta = dict(row.get("metadata") or {})
    feats = dict(row.get("features") or {})
    evidence = apply_all_depth_engines(feats, None, meta)
    tags: list[str] = []
    hits: list[str] = []
    merge_depth_into_score_and_tags(
        evidence=evidence, all_new_tags=tags, rule_hits=hits
    )

    expect = row.get("expect") or {}
    for key in expect.get("evidence_keys") or []:
        assert key in evidence, f"{cid}: missing evidence key {key}"

    for f in expect.get("features_true") or []:
        assert feats.get(f) is True, (
            f"{cid}: expected feature true: {f} (got {feats.get(f)!r})"
        )

    for f in expect.get("features_false") or []:
        assert feats.get(f) is not True, f"{cid}: expected feature not true: {f}"

    typ_res = evaluate_typologies(hits, feats)
    by_id = {t["id"]: t for t in typ_res}

    for tid, min_level in (expect.get("typology_min_breach") or {}).items():
        row_t = by_id.get(tid)
        assert row_t is not None, f"{cid}: missing typology {tid}"
        got = str(row_t.get("breach_level") or "pass")
        assert _BREACH_RANK[got] >= _BREACH_RANK[min_level], (
            f"{cid}: typology {tid} breach {got} < min {min_level}"
        )

    for tid, max_level in (expect.get("typology_max_breach") or {}).items():
        row_t = by_id.get(tid)
        assert row_t is not None, f"{cid}: missing typology {tid}"
        got = str(row_t.get("breach_level") or "pass")
        assert _BREACH_RANK[got] <= _BREACH_RANK[max_level], (
            f"{cid}: typology {tid} breach {got} > max {max_level}"
        )


@pytest.mark.parametrize("corpus", _CORPORA)
def test_depth_golden_corpus(corpus: str):
    for row in _load_rows(corpus):
        _run_case(row)


def test_depth_golden_corpora_cover_verticals():
    seen: set[str] = set()
    for name in _CORPORA:
        for row in _load_rows(name):
            v = str(row.get("vertical") or "")
            assert v, f"{name}: row missing vertical"
            seen.add(v)
    assert {
        "marketplace_goods",
        "food_delivery",
        "last_mile",
        "e_hailing",
    } <= seen


def test_depth_engines_ops_posture_honesty():
    from decision_api.depth_engines_ops import load_depth_engines_ops_posture

    body = load_depth_engines_ops_posture()
    assert body["schema_id"] == "tarka.depth_engines_ops/v1"
    assert body["engine_count"] == 8
    assert body["honesty"]["forged_live_forbidden"] is True
    ids = {e["engine_id"] for e in body["engines"]}
    assert ids == {
        "lifecycle_risk",
        "ring_score",
        "seller_trajectory",
        "ftid_intake_gate",
        "promo_economics",
        "dispute_representment",
        "listing_risk",
        "depth_fusion",
    }
    assert all(e["live_claim_allowed"] is False for e in body["engines"])
    assert all(e["gnn_claim_allowed"] is False for e in body["engines"])
