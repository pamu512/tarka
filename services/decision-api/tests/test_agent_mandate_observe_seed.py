"""Observe-only agent mandate seed: out of mandate stays shadow and locked."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
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
_NAME = "seed_agent_mandate_observe_v1.json"


def _load() -> dict:
    return json.loads((_RULES / _NAME).read_text(encoding="utf-8"))


def _hits(features: dict) -> list[str]:
    hits, _tags, _delta, _pf = evaluate_adhoc_packs_json([_load()], features, [])
    return hits


def test_seed_stays_shadow_and_fields_are_registered(monkeypatch):
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
        for cond in rule["when"]:
            assert cond["field"] in allowed


def test_missing_actor_does_not_hit_and_is_not_human():
    hits, _tags, delta, _pf = evaluate_adhoc_packs_json([_load()], {}, [])
    assert hits == []
    assert delta == 0
    assert _hits({"actor_kind": "human"}) == []
    assert _hits({"actor_kind": ""}) == []


def test_missing_caps_is_observe_not_in_mandate():
    hits, _tags, delta, _pf = evaluate_adhoc_packs_json(
        [_load()], {"actor_kind": "agent"}, []
    )
    assert "seed_agent_out_of_mandate_caps" in hits
    assert "seed_agent_out_of_mandate_expiry" not in hits
    assert delta == 8


def test_past_expiry_is_observe_not_in_mandate():
    features = {
        "actor_kind": "agent",
        "mandate_caps": {"spend_limit": 10},
        "mandate_expired": True,
    }
    hits, _tags, delta, _pf = evaluate_adhoc_packs_json([_load()], features, [])
    assert hits == ["seed_agent_out_of_mandate_expiry"]
    assert delta == 8


def test_future_expiry_without_caps_is_still_out_of_mandate():
    hits, _tags, delta, _pf = evaluate_adhoc_packs_json(
        [_load()],
        {
            "actor_kind": "agent",
            "mandate_expires_at": "2099-01-01T00:00:00+00:00",
        },
        [],
    )
    assert "seed_agent_out_of_mandate_caps" in hits
    assert delta == 8


def test_in_mandate_does_not_hit_observe_rules():
    features = {
        "actor_kind": "agent",
        "mandate_caps": {"spend_limit": 10},
        "mandate_expires_at": "2099-01-01T00:00:00+00:00",
    }
    hits, _tags, delta, _pf = evaluate_adhoc_packs_json([_load()], features, [])
    assert hits == []
    assert delta == 0


def test_observe_receipt_does_not_rewrite_production_decision():
    hits = _hits({"actor_kind": "agent"})
    record_observation(
        "trace-agent-mandate",
        {"decision": "review", "score": 40},
        {"shadow_decision": "review", "shadow_rule_hits": hits},
    )
    rows = [row for row in get_observations(10000) if row.get("trace_id") == "trace-agent-mandate"]
    assert rows[-1]["production_decision"] == "review"
    assert rows[-1]["production_score"] == 40


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
        activate_shadow_pack("seed_agent_mandate_observe", actor="ops", reason="nope")
    assert json.loads(dest.read_text(encoding="utf-8"))["mode"] == "shadow"
