"""Observe-only gift/store-credit cash-out seed: refund/payout tendered as a bearer instrument."""

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
_NAME = "seed_gift_store_credit_cashout_observe_v1.json"


def _load() -> dict:
    return json.loads((_RULES / _NAME).read_text(encoding="utf-8"))


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
    assert "instrument_kind" in seed_names()
    assert "instrument_kind" in PAYLOAD_FIELDS
    assert {r["id"] for r in pack["rules"]} == {
        "seed_refund_gift_store_credit_cashout",
        "seed_payout_gift_store_credit_cashout",
    }


def test_refund_with_gift_card_or_store_credit_hits():
    assert _hits({"event_type": "refund", "instrument_kind": "gift_card"}) == [
        "seed_refund_gift_store_credit_cashout"
    ]
    assert _hits({"event_type": "refund", "instrument_kind": "store_credit"}) == [
        "seed_refund_gift_store_credit_cashout"
    ]


def test_payout_with_gift_card_or_store_credit_hits():
    assert _hits({"event_type": "payout", "instrument_kind": "gift_card"}) == [
        "seed_payout_gift_store_credit_cashout"
    ]
    assert _hits({"event_type": "payout", "instrument_kind": "store_credit"}) == [
        "seed_payout_gift_store_credit_cashout"
    ]


def test_fail_closed_when_instrument_kind_is_missing_or_empty():
    hits, _tags, delta, _pf = evaluate_adhoc_packs_json(
        [_load()], {"event_type": "refund"}, []
    )
    assert hits == []
    assert delta == 0
    assert _hits({"event_type": "refund"}) == []
    assert _hits({"event_type": "refund", "instrument_kind": ""}) == []
    assert _hits({"event_type": "payout"}) == []
    assert _hits({"event_type": "payout", "instrument_kind": ""}) == []
    assert _hits({}) == []


def test_other_tenders_do_not_hit():
    for tender in ("card", "bank", "cash", "wallet", "crypto", "cheque"):
        assert _hits({"event_type": "refund", "instrument_kind": tender}) == []
        assert _hits({"event_type": "payout", "instrument_kind": tender}) == []


def test_wrong_event_type_with_gift_card_tender_does_not_hit():
    assert _hits({"event_type": "payment", "instrument_kind": "gift_card"}) == []
    assert _hits({"event_type": "promo", "instrument_kind": "gift_card"}) == []
    assert _hits({"event_type": "claim", "instrument_kind": "store_credit"}) == []


def test_case_and_whitespace_tender_values_do_not_hit():
    assert _hits({"event_type": "refund", "instrument_kind": "Gift_Card"}) == []
    assert _hits({"event_type": "payout", "instrument_kind": " gift_card "}) == []


def test_observe_receipt_does_not_rewrite_production_decision():
    hits = _hits({"event_type": "refund", "instrument_kind": "gift_card"})
    record_observation(
        "trace-gift-cashout",
        {"decision": "allow", "score": 5},
        {"shadow_decision": "review", "shadow_rule_hits": hits},
    )
    rows = [
        row
        for row in get_observations(10000)
        if row.get("trace_id") == "trace-gift-cashout"
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
            "seed_gift_store_credit_cashout_observe", actor="ops", reason="nope"
        )
    assert json.loads(dest.read_text(encoding="utf-8"))["mode"] == "shadow"
