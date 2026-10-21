"""Beachhead Observe seeds stay shadow and registry-keyed."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from decision_api.json_rules import evaluate_adhoc_packs_json
from decision_api.rule_pack_validation import validate_rule_pack
from field_registry import seed_names
from tarka_shared.ingest_contract_v1 import allowed_event_types

_RULES = Path(__file__).resolve().parents[1] / "rules"
_SEEDS = (
    "seed_promo_observe_v1.json",
    "seed_cod_observe_v1.json",
    "seed_payout_observe_v1.json",
    "seed_refund_observe_v1.json",
    "seed_ato_observe_v1.json",
    "seed_delivery_observe_v1.json",
    "seed_collusion_observe_v1.json",
    "seed_claims_observe_v1.json",
    "seed_refund_instrument_ato_observe_v1.json",
)
_BEACHHEAD_TYPES = ("promo", "cod", "payout", "order", "delivery", "refund", "claim")


def _load(name: str) -> dict:
    return json.loads((_RULES / name).read_text(encoding="utf-8"))


def _eval_claims_pack(features: dict) -> list[str]:
    # Adhoc path keeps shadow packs evaluable; production evaluate excludes them.
    pack = _load("seed_claims_observe_v1.json")
    hits, _tags, _delta, _pf = evaluate_adhoc_packs_json([pack], features, [])
    return hits


def test_beachhead_event_types_are_registry_allowed():
    allowed = allowed_event_types()
    for name in _BEACHHEAD_TYPES:
        assert name in allowed
    assert "not_a_real_type" not in allowed


def test_unknown_event_type_still_422():
    from fastapi import HTTPException

    from decision_api.event_type_gate import raise_if_event_type_not_allowed

    with pytest.raises(HTTPException) as exc:
        raise_if_event_type_not_allowed("not_a_real_type")
    assert exc.value.status_code == 422


def test_beachhead_seeds_are_observe_never_active(tmp_path, monkeypatch):
    from decision_api import json_rules
    from decision_api.config import settings

    monkeypatch.setattr(settings, "rules_path", str(_RULES))
    json_rules.load_rules()
    shadow = {p.get("name") for p in json_rules.get_shadow_packs()}
    active = {p.get("name") for p in json_rules.get_active_packs_snapshot()}
    for fname in _SEEDS:
        pack = _load(fname)
        assert pack["mode"] == "shadow"
        assert pack["authored_by"] == "seed"
        assert "Promote to live" in pack["author_notes"]
        assert pack["name"] in shadow
        assert pack["name"] not in active
        assert validate_rule_pack(pack) == []
        allowed = seed_names()
        for rule in pack.get("rules") or []:
            for cond in rule.get("when") or []:
                assert cond["field"] in allowed


def test_claims_observe_join_hit_stays_shadow():
    pack = _load("seed_claims_observe_v1.json")
    assert pack["mode"] == "shadow"
    assert validate_rule_pack(pack) == []
    hits = _eval_claims_pack(
        {"event_type": "claim", "amount": 150, "pod_integrity_fail": True}
    )
    assert "seed_claims_pod_join" in hits


def test_claims_observe_fail_closed_missing_pod():
    hits = _eval_claims_pack({"event_type": "claim", "amount": 150})
    assert "seed_claims_pod_join" not in hits


def test_claims_observe_fail_closed_missing_amount_or_wrong_event():
    assert "seed_claims_pod_join" not in _eval_claims_pack(
        {"event_type": "claim", "pod_integrity_fail": True}
    )
    assert "seed_claims_pod_join" not in _eval_claims_pack(
        {"event_type": "refund", "amount": 150, "pod_integrity_fail": True}
    )


def _eval_refund_instrument_ato_pack(features: dict) -> list[str]:
    pack = _load("seed_refund_instrument_ato_observe_v1.json")
    hits, _tags, _delta, _pf = evaluate_adhoc_packs_json([pack], features, [])
    return hits


def test_refund_instrument_ato_observe_join_hits_stay_shadow():
    pack = _load("seed_refund_instrument_ato_observe_v1.json")
    assert pack["mode"] == "shadow"
    assert pack["is_ai_authored"] is False
    assert "observe_locked" not in pack
    assert validate_rule_pack(pack) == []
    assert [rule["id"] for rule in pack["rules"]] == [
        "seed_refund_to_different_instrument",
        "seed_ato_to_refund",
    ]
    for rule in pack["rules"]:
        assert str(rule.get("description") or "").strip()
    mismatch = _eval_refund_instrument_ato_pack(
        {"event_type": "refund", "refund_instrument_mismatch": True}
    )
    assert "seed_refund_to_different_instrument" in mismatch
    assert "seed_ato_to_refund" not in mismatch
    ato = _eval_refund_instrument_ato_pack({"event_type": "refund", "recent_ato": True})
    assert "seed_ato_to_refund" in ato
    assert "seed_refund_to_different_instrument" not in ato
    both = _eval_refund_instrument_ato_pack(
        {
            "event_type": "refund",
            "refund_instrument_mismatch": True,
            "recent_ato": True,
        }
    )
    assert "seed_refund_to_different_instrument" in both
    assert "seed_ato_to_refund" in both


def test_refund_instrument_ato_fail_closed_missing_or_wrong_event():
    assert _eval_refund_instrument_ato_pack({"event_type": "refund"}) == []
    assert (
        _eval_refund_instrument_ato_pack(
            {"event_type": "refund", "refund_instrument_mismatch": False, "recent_ato": False}
        )
        == []
    )
    assert (
        _eval_refund_instrument_ato_pack(
            {"refund_instrument_mismatch": True, "recent_ato": True}
        )
        == []
    )
    assert (
        _eval_refund_instrument_ato_pack(
            {
                "event_type": "login",
                "refund_instrument_mismatch": True,
                "recent_ato": True,
            }
        )
        == []
    )


def test_refund_instrument_ato_fail_closed_null_and_non_bool():
    absent = {"event_type": "refund", "refund_instrument_mismatch": None, "recent_ato": None}
    assert _eval_refund_instrument_ato_pack(absent) == []
    stringy = {
        "event_type": "refund",
        "refund_instrument_mismatch": "true",
        "recent_ato": "true",
    }
    assert _eval_refund_instrument_ato_pack(stringy) == []
    numeric = {"event_type": "refund", "refund_instrument_mismatch": 1, "recent_ato": 1}
    assert _eval_refund_instrument_ato_pack(numeric) == []
    wrong_case = {
        "event_type": "Refund",
        "refund_instrument_mismatch": True,
        "recent_ato": True,
    }
    assert _eval_refund_instrument_ato_pack(wrong_case) == []


def test_refund_instrument_ato_fields_registered_fail_closed():
    registry_path = (
        Path(__file__).resolve().parents[1]
        / "src"
        / "decision_api"
        / "data"
        / "field_registry_v1.json"
    )
    rows = [
        row
        for row in json.loads(registry_path.read_text(encoding="utf-8"))
        if row.get("name") in {"refund_instrument_mismatch", "recent_ato"}
    ]
    assert sorted(row["name"] for row in rows) == ["recent_ato", "refund_instrument_mismatch"]
    for row in rows:
        assert row["source"] == "tarka_core"
        explanation = str(row.get("explanation") or "")
        assert "missing" in explanation
        assert "fail-closed" in explanation


def test_amount_refund_and_login_ato_seeds_stay_independent():
    packs = [
        _load("seed_refund_observe_v1.json"),
        _load("seed_ato_observe_v1.json"),
        _load("seed_refund_instrument_ato_observe_v1.json"),
    ]
    amount_hits, _tags, _delta, _pf = evaluate_adhoc_packs_json(
        packs, {"event_type": "refund", "amount": 200}, []
    )
    assert "seed_refund_amount" in amount_hits
    assert "seed_refund_to_different_instrument" not in amount_hits
    assert "seed_ato_to_refund" not in amount_hits
    login_hits, _tags, _delta, _pf = evaluate_adhoc_packs_json(
        packs, {"event_type": "login", "event_count_1h": 20}, []
    )
    assert "seed_ato_velocity" in login_hits
    assert "seed_ato_to_refund" not in login_hits
    assert "seed_refund_to_different_instrument" not in login_hits
