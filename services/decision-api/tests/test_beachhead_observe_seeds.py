"""Beachhead Observe seeds: promo / COD / payout / claims stay shadow and registry-keyed."""

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
    "seed_ai_claim_evidence_observe_v1.json",
)
_BEACHHEAD_TYPES = ("promo", "cod", "payout", "order", "delivery", "refund", "claim")


def _load(name: str) -> dict:
    return json.loads((_RULES / name).read_text(encoding="utf-8"))


def _eval_claims_pack(features: dict) -> list[str]:
    # Adhoc path keeps shadow packs evaluable; production evaluate excludes them.
    pack = _load("seed_claims_observe_v1.json")
    hits, _tags, _delta, _pf = evaluate_adhoc_packs_json([pack], features, [])
    return hits


def _eval_ai_claim_evidence_pack(features: dict) -> list[str]:
    pack = _load("seed_ai_claim_evidence_observe_v1.json")
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


def test_ai_claim_evidence_observe_join_hits_stay_shadow():
    pack = _load("seed_ai_claim_evidence_observe_v1.json")
    assert pack["mode"] == "shadow"
    assert pack["is_ai_authored"] is False
    assert validate_rule_pack(pack) == []
    assert "seed_false_nad_claim" in _eval_ai_claim_evidence_pack(
        {"event_type": "claim", "false_nad": True}
    )
    assert "seed_synthetic_receipt_evidence" in _eval_ai_claim_evidence_pack(
        {"event_type": "claim", "synthetic_receipt_evidence": True}
    )
    assert "seed_synthetic_damage_evidence" in _eval_ai_claim_evidence_pack(
        {"event_type": "claim", "synthetic_damage_evidence": True}
    )


def test_ai_claim_evidence_fail_closed_missing_flags_and_wrong_event():
    assert _eval_ai_claim_evidence_pack({"event_type": "claim"}) == []
    assert (
        _eval_ai_claim_evidence_pack(
            {
                "event_type": "refund",
                "false_nad": True,
                "synthetic_receipt_evidence": True,
                "synthetic_damage_evidence": True,
            }
        )
        == []
    )
    assert (
        _eval_ai_claim_evidence_pack(
            {
                "event_type": "login",
                "false_nad": True,
                "synthetic_receipt_evidence": True,
                "synthetic_damage_evidence": True,
            }
        )
        == []
    )


def test_ai_claim_evidence_fail_closed_null_and_non_bool():
    absent = {
        "event_type": "claim",
        "false_nad": None,
        "synthetic_receipt_evidence": None,
        "synthetic_damage_evidence": None,
    }
    assert _eval_ai_claim_evidence_pack(absent) == []
    stringy = {
        "event_type": "claim",
        "false_nad": "true",
        "synthetic_receipt_evidence": "true",
        "synthetic_damage_evidence": "true",
    }
    assert _eval_ai_claim_evidence_pack(stringy) == []
    numeric = {
        "event_type": "claim",
        "false_nad": 1,
        "synthetic_receipt_evidence": 1,
        "synthetic_damage_evidence": 1,
    }
    assert _eval_ai_claim_evidence_pack(numeric) == []
    wrong_case = {
        "event_type": "Claim",
        "false_nad": True,
        "synthetic_receipt_evidence": True,
        "synthetic_damage_evidence": True,
    }
    assert _eval_ai_claim_evidence_pack(wrong_case) == []


def test_ai_claim_evidence_fields_registered_fail_closed():
    registry_path = (
        Path(__file__).resolve().parents[1]
        / "src"
        / "decision_api"
        / "data"
        / "field_registry_v1.json"
    )
    wanted = {
        "false_nad",
        "synthetic_receipt_evidence",
        "synthetic_damage_evidence",
    }
    rows = [
        row
        for row in json.loads(registry_path.read_text(encoding="utf-8"))
        if row.get("name") in wanted
    ]
    assert sorted(row["name"] for row in rows) == sorted(wanted)
    for row in rows:
        assert row["source"] == "tarka_core"
        explanation = str(row.get("explanation") or "")
        assert "missing" in explanation
        assert "fail-closed" in explanation


def test_claims_pod_seed_stays_independent_of_ai_claim_evidence():
    packs = [
        _load("seed_claims_observe_v1.json"),
        _load("seed_ai_claim_evidence_observe_v1.json"),
    ]
    hits, _tags, _delta, _pf = evaluate_adhoc_packs_json(
        packs,
        {"event_type": "claim", "amount": 150, "pod_integrity_fail": True},
        [],
    )
    assert "seed_claims_pod_join" in hits
    assert "seed_false_nad_claim" not in hits
    assert "seed_synthetic_receipt_evidence" not in hits
    assert "seed_synthetic_damage_evidence" not in hits
