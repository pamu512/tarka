"""Observe-only promo stacking / first-order new-account seed stays shadow and locked."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from author_catalog import PAYLOAD_FIELDS
from decision_api.json_rules import evaluate_adhoc_packs_json
from decision_api.rule_pack_validation import validate_rule_pack
from decision_api.shadow import get_observations, record_observation
from decision_api.shadow_auto_promote import (
    ObserveLocked,
    activate_shadow_pack,
    shadow_packs_eligible_for_auto_promote,
)
from field_registry import seed_names

_RULES = Path(__file__).resolve().parents[1] / "rules"
_NAME = "seed_promo_stacking_first_order_observe_v1.json"
_PROMO_OBSERVE = "seed_promo_observe_v1.json"
_FIELDS = ("first_order_promo", "new_account", "coupon_stack")


def _load(name: str = _NAME) -> dict:
    return json.loads((_RULES / name).read_text(encoding="utf-8"))


def _hits(features: dict) -> list[str]:
    hits, _tags, _delta, _pf = evaluate_adhoc_packs_json([_load()], features, [])
    return hits


def test_seed_stays_shadow_locked_and_fields_are_registered(monkeypatch):
    from decision_api import json_rules
    from decision_api.config import settings

    monkeypatch.setattr(settings, "rules_path", str(_RULES))
    json_rules.load_rules()
    pack = _load()
    assert pack["mode"] == "shadow"
    assert pack["observe_locked"] is True
    assert pack["authored_by"] == "seed"
    assert pack["is_ai_authored"] is False
    assert "Promote to live" not in pack["author_notes"]
    shadow = {p.get("name") for p in json_rules.get_shadow_packs()}
    active = {p.get("name") for p in json_rules.get_active_packs_snapshot()}
    assert pack["name"] in shadow
    assert pack["name"] not in active
    assert validate_rule_pack(pack) == []
    allowed = seed_names()
    for rule in pack["rules"]:
        assert rule["description"].strip()
        for cond in rule["when"]:
            assert cond["field"] in allowed
            if cond["field"] in _FIELDS:
                assert cond["op"] == "eq"
                assert cond["value"] is True
            assert cond["op"] not in ("not_in", "not_exists")
    for name in _FIELDS:
        assert name in seed_names()
        assert name in PAYLOAD_FIELDS
    assert {r["id"] for r in pack["rules"]} == {
        "seed_promo_first_order_new_account",
        "seed_promo_coupon_stack",
    }


def test_first_order_new_account_promo_hits_rule_one():
    assert _hits(
        {
            "event_type": "promo",
            "first_order_promo": True,
            "new_account": True,
        }
    ) == ["seed_promo_first_order_new_account"]


def test_coupon_stack_promo_hits_rule_two():
    assert _hits({"event_type": "promo", "coupon_stack": True}) == [
        "seed_promo_coupon_stack"
    ]


def test_redeem_with_both_flags_may_hit_both_rules():
    hits = _hits(
        {
            "event_type": "promo",
            "first_order_promo": True,
            "new_account": True,
            "coupon_stack": True,
        }
    )
    assert set(hits) == {
        "seed_promo_first_order_new_account",
        "seed_promo_coupon_stack",
    }


def test_fail_closed_when_required_fields_missing_empty_or_false():
    hits, _tags, delta, _pf = evaluate_adhoc_packs_json(
        [_load()], {"event_type": "promo"}, []
    )
    assert hits == []
    assert delta == 0
    assert _hits({"event_type": "promo"}) == []
    assert _hits({"event_type": "promo", "first_order_promo": ""}) == []
    assert _hits({"event_type": "promo", "new_account": ""}) == []
    assert _hits({"event_type": "promo", "coupon_stack": ""}) == []
    assert _hits({"event_type": "promo", "first_order_promo": False}) == []
    assert _hits({"event_type": "promo", "new_account": False}) == []
    assert _hits({"event_type": "promo", "coupon_stack": False}) == []
    assert _hits({}) == []


def test_partial_first_order_without_new_account_does_not_hit_rule_one():
    assert _hits({"event_type": "promo", "first_order_promo": True}) == []
    assert (
        _hits(
            {
                "event_type": "promo",
                "first_order_promo": True,
                "new_account": False,
            }
        )
        == []
    )
    assert (
        _hits(
            {
                "event_type": "promo",
                "first_order_promo": True,
                "new_account": "",
            }
        )
        == []
    )


def test_coupon_stack_true_alone_hits_rule_two_only():
    hits = _hits({"event_type": "promo", "coupon_stack": True})
    assert hits == ["seed_promo_coupon_stack"]
    assert "seed_promo_first_order_new_account" not in hits


def test_amount_only_promo_does_not_hit_this_pack():
    assert _hits({"event_type": "promo", "amount": 250}) == []
    assert _hits({"event_type": "promo", "amount": 999}) == []


def test_wrong_event_with_flags_does_not_hit():
    flags = {
        "first_order_promo": True,
        "new_account": True,
        "coupon_stack": True,
    }
    assert _hits({"event_type": "payment", **flags}) == []
    assert _hits({"event_type": "signup", **flags}) == []
    assert _hits({"event_type": "refund", **flags}) == []


def test_seed_promo_observe_amount_pack_is_unchanged():
    pack = _load(_PROMO_OBSERVE)
    assert pack["name"] == "seed_promo_observe"
    assert pack["author_notes"] == "Promote to live; seeds are Observe."
    assert "observe_locked" not in pack
    assert [r["id"] for r in pack["rules"]] == ["seed_promo_amount"]
    hits, _tags, _delta, _pf = evaluate_adhoc_packs_json(
        [pack], {"event_type": "promo", "amount": 250}, []
    )
    assert hits == ["seed_promo_amount"]
    stacking_hits, _t, _d, _p = evaluate_adhoc_packs_json(
        [_load()], {"event_type": "promo", "amount": 250}, []
    )
    assert stacking_hits == []


def test_observe_receipt_does_not_rewrite_production_decision():
    hits = _hits(
        {
            "event_type": "promo",
            "first_order_promo": True,
            "new_account": True,
        }
    )
    record_observation(
        "trace-promo-stacking",
        {"decision": "allow", "score": 5},
        {"shadow_decision": "review", "shadow_rule_hits": hits},
    )
    rows = [
        row
        for row in get_observations(10000)
        if row.get("trace_id") == "trace-promo-stacking"
    ]
    assert rows[-1]["production_decision"] == "allow"
    assert rows[-1]["production_score"] == 5


def test_auto_promote_skips_observe_locked_seed():
    locked = _load()
    locked["is_ai_authored"] = True
    other = {"name": "ai_draft", "is_ai_authored": True}
    assert shadow_packs_eligible_for_auto_promote([locked, other]) == ["ai_draft"]


def test_activate_refuses_observe_locked(tmp_path, monkeypatch):
    from decision_api import json_rules
    from decision_api.config import settings

    dest = tmp_path / _NAME
    dest.write_text((_RULES / _NAME).read_text(encoding="utf-8"), encoding="utf-8")
    monkeypatch.setattr(settings, "rules_path", str(tmp_path))
    json_rules.load_rules()
    with pytest.raises(ObserveLocked):
        activate_shadow_pack(
            "seed_promo_stacking_first_order_observe", actor="ops", reason="nope"
        )
    assert json.loads(dest.read_text(encoding="utf-8"))["mode"] == "shadow"
