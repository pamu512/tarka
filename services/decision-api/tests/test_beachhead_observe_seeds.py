"""Beachhead Observe seed packs (promo/COD/payout/refund/ATO/delivery/collusion/claims/AI-claim-evidence/merchant-truth-claim) stay shadow and registry-keyed."""

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
    "seed_merchant_truth_claim_observe_v1.json",
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


def _eval_merchant_truth_pack(features: dict) -> list[str]:
    pack = _load("seed_merchant_truth_claim_observe_v1.json")
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


def test_merchant_truth_observe_join_hits_stay_shadow():
    pack = _load("seed_merchant_truth_claim_observe_v1.json")
    assert pack["mode"] == "shadow"
    assert pack["is_ai_authored"] is False
    assert validate_rule_pack(pack) == []
    # PackWhy fence: every rule carries a non-empty desk-readable description.
    for rule in pack["rules"]:
        assert str(rule.get("description") or "").strip()
    assert "seed_nad_vs_merchant_delivery" in _eval_merchant_truth_pack(
        {"event_type": "claim", "false_nad": True, "merchant_delivery_confirmed": True}
    )
    assert "seed_synthetic_receipt_vs_merchant_checkout" in _eval_merchant_truth_pack(
        {
            "event_type": "claim",
            "synthetic_receipt_evidence": True,
            "merchant_checkout_session_ok": True,
        }
    )
    assert "seed_synthetic_damage_vs_merchant_payment" in _eval_merchant_truth_pack(
        {
            "event_type": "claim",
            "synthetic_damage_evidence": True,
            "merchant_payment_record_match": True,
        }
    )


def test_merchant_truth_fail_closed_missing_merchant_signal():
    # Missing retailer truth = absent, never risky-because-silent.
    assert (
        _eval_merchant_truth_pack({"event_type": "claim", "false_nad": True})
        == []
    )
    assert (
        _eval_merchant_truth_pack(
            {"event_type": "claim", "synthetic_receipt_evidence": True}
        )
        == []
    )
    assert (
        _eval_merchant_truth_pack(
            {"event_type": "claim", "synthetic_damage_evidence": True}
        )
        == []
    )


def test_merchant_truth_fail_closed_missing_claim_flag_and_wrong_event():
    # Missing #535 flag: no hit even when merchant truth is present.
    assert (
        _eval_merchant_truth_pack(
            {"event_type": "claim", "merchant_delivery_confirmed": True}
        )
        == []
    )
    assert (
        _eval_merchant_truth_pack(
            {
                "event_type": "refund",
                "false_nad": True,
                "synthetic_receipt_evidence": True,
                "synthetic_damage_evidence": True,
                "merchant_delivery_confirmed": True,
                "merchant_checkout_session_ok": True,
                "merchant_payment_record_match": True,
            }
        )
        == []
    )


def test_merchant_truth_fail_closed_null_and_non_bool():
    nulls = {
        "event_type": "claim",
        "false_nad": True,
        "synthetic_receipt_evidence": True,
        "synthetic_damage_evidence": True,
        "merchant_delivery_confirmed": None,
        "merchant_checkout_session_ok": None,
        "merchant_payment_record_match": None,
    }
    assert _eval_merchant_truth_pack(nulls) == []
    stringy = {
        "event_type": "claim",
        "false_nad": True,
        "merchant_delivery_confirmed": "true",
    }
    assert _eval_merchant_truth_pack(stringy) == []
    numeric = {
        "event_type": "claim",
        "false_nad": True,
        "merchant_delivery_confirmed": 1,
    }
    assert _eval_merchant_truth_pack(numeric) == []
    wrong_case = {
        "event_type": "Claim",
        "false_nad": True,
        "merchant_delivery_confirmed": True,
    }
    assert _eval_merchant_truth_pack(wrong_case) == []


def test_merchant_truth_fields_registered_fail_closed():
    registry_path = (
        Path(__file__).resolve().parents[1]
        / "src"
        / "decision_api"
        / "data"
        / "field_registry_v1.json"
    )
    wanted = {
        "merchant_delivery_confirmed",
        "merchant_checkout_session_ok",
        "merchant_payment_record_match",
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


def test_merchant_truth_stays_independent_of_claims_and_ai_claim_evidence():
    packs = [
        _load("seed_claims_observe_v1.json"),
        _load("seed_ai_claim_evidence_observe_v1.json"),
        _load("seed_merchant_truth_claim_observe_v1.json"),
    ]
    # AI-claim flags without merchant truth fire only the AI-claim seed.
    ai_only = {
        "event_type": "claim",
        "false_nad": True,
        "synthetic_receipt_evidence": True,
        "synthetic_damage_evidence": True,
    }
    hits, _tags, _delta, _pf = evaluate_adhoc_packs_json(packs, ai_only, [])
    assert "seed_false_nad_claim" in hits
    assert "seed_synthetic_receipt_evidence" in hits
    assert "seed_synthetic_damage_evidence" in hits
    assert "seed_nad_vs_merchant_delivery" not in hits
    assert "seed_synthetic_receipt_vs_merchant_checkout" not in hits
    assert "seed_synthetic_damage_vs_merchant_payment" not in hits
    # Full merchant-truth join fires the merchant seed only (no amount/POD,
    # no bare AI-claim ids from this pack).
    join = {
        "event_type": "claim",
        "false_nad": True,
        "merchant_delivery_confirmed": True,
    }
    hits, _tags, _delta, _pf = evaluate_adhoc_packs_json(packs, join, [])
    assert "seed_nad_vs_merchant_delivery" in hits
    assert "seed_claims_pod_join" not in hits
