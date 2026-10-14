"""Tests for the AI pack-author contract validator.

Covers: valid shadow pack passes; live mode rejected; unknown field/op rejected;
score_delta over cap rejected; missing is_ai_authored rejected; empty rules rejected;
scout suggested_shadow_rule template validation.
"""

from __future__ import annotations

import asyncio
import copy
import json

import pytest

from pack_author_contract import (
    ALLOWED_FIELDS,
    ALLOWED_OPS,
    SCORE_DELTA_MAX,
    SCORE_DELTA_MIN,
    load_contract_text,
    validate_ai_authored_pack,
    validate_suggested_shadow_rule_template,
    ai_authored_pack_json_schema,
    build_llm_directive,
    classify_sop_chunks,
    evidence_is_thin,
    sop_draft_errors,
)
from pack_author_llm import author_pack_from_hypothesis


def _valid_pack() -> dict:
    return {
        "name": "test_pack",
        "version": 1,
        "mode": "shadow",
        "is_ai_authored": True,
        "authored_by": "scout",
        "rules": [
            {
                "id": "r1",
                "when": [{"field": "canvas_hash", "op": "eq", "value": "abc123"}],
                "score_delta": 25,
            }
        ],
    }


# --- contract file loads ---


def test_contract_text_loads():
    text = load_contract_text()
    assert "AI Pack-Author Contract" in text
    assert "shadow" in text
    assert "leftover helpfulness" in text


# --- valid pack passes ---


def test_valid_shadow_pack_passes():
    result = validate_ai_authored_pack(_valid_pack())
    assert result["ok"] is True
    assert result["pack"]["mode"] == "shadow"
    assert result["pack"]["is_ai_authored"] is True


def test_valid_pack_with_all_optional_fields():
    pack = _valid_pack()
    pack["description"] = "Test description"
    pack["evidence"] = {"report_id": "rpt-1", "count": 5}
    pack["rules"][0]["description"] = "Some rule"
    pack["rules"][0]["tags"] = ["test:tag"]
    pack["rules"][0]["metadata"] = {"source": "scout"}
    result = validate_ai_authored_pack(pack)
    assert result["ok"] is True


# --- mode enforcement ---


def test_live_mode_rejected():
    pack = _valid_pack()
    pack["mode"] = "active"
    result = validate_ai_authored_pack(pack)
    assert result["ok"] is False
    assert any("mode" in e.lower() or "shadow" in e.lower() for e in result["errors"])


def test_disabled_mode_rejected():
    pack = _valid_pack()
    pack["mode"] = "disabled"
    result = validate_ai_authored_pack(pack)
    assert result["ok"] is False


def test_mode_missing_defaults_shadow():
    pack = _valid_pack()
    del pack["mode"]
    result = validate_ai_authored_pack(pack)
    assert result["ok"] is True
    assert result["pack"]["mode"] == "shadow"


# --- is_ai_authored enforcement ---


def test_missing_is_ai_authored_rejected():
    pack = _valid_pack()
    del pack["is_ai_authored"]
    result = validate_ai_authored_pack(pack)
    assert result["ok"] is False


def test_false_is_ai_authored_rejected():
    pack = _valid_pack()
    pack["is_ai_authored"] = False
    result = validate_ai_authored_pack(pack)
    assert result["ok"] is False


# --- empty rules rejected ---


def test_empty_rules_rejected():
    pack = _valid_pack()
    pack["rules"] = []
    result = validate_ai_authored_pack(pack)
    assert result["ok"] is False


def test_missing_rules_rejected():
    pack = _valid_pack()
    del pack["rules"]
    result = validate_ai_authored_pack(pack)
    assert result["ok"] is False


# --- score_delta bounds ---


def test_score_delta_over_cap_rejected():
    pack = _valid_pack()
    pack["rules"][0]["score_delta"] = 100
    result = validate_ai_authored_pack(pack)
    assert result["ok"] is False


def test_score_delta_at_max_passes():
    pack = _valid_pack()
    pack["rules"][0]["score_delta"] = SCORE_DELTA_MAX
    result = validate_ai_authored_pack(pack)
    assert result["ok"] is True


def test_score_delta_at_min_passes():
    pack = _valid_pack()
    pack["rules"][0]["score_delta"] = SCORE_DELTA_MIN
    result = validate_ai_authored_pack(pack)
    assert result["ok"] is True


def test_score_delta_below_min_rejected():
    pack = _valid_pack()
    pack["rules"][0]["score_delta"] = 1
    result = validate_ai_authored_pack(pack)
    assert result["ok"] is False


def test_score_delta_negative_rejected():
    pack = _valid_pack()
    pack["rules"][0]["score_delta"] = -50
    result = validate_ai_authored_pack(pack)
    assert result["ok"] is False


def test_deny_100_rejected():
    """Deny-100 / blacklist writes are forbidden."""
    pack = _valid_pack()
    pack["rules"][0]["score_delta"] = 100
    result = validate_ai_authored_pack(pack)
    assert result["ok"] is False


# --- unknown field rejected ---


def test_unknown_field_rejected():
    pack = _valid_pack()
    pack["rules"][0]["when"] = [{"field": "consortium_score", "op": "gte", "value": 50}]
    result = validate_ai_authored_pack(pack)
    assert result["ok"] is False
    assert any("unknown field" in e for e in result["errors"])


def test_invented_kyc_field_rejected():
    pack = _valid_pack()
    pack["rules"][0]["when"] = [{"field": "kyc_verified", "op": "is_true"}]
    result = validate_ai_authored_pack(pack)
    assert result["ok"] is False


def test_allowed_fields_override_accepts_order_channel():
    pack = _valid_pack()
    pack["rules"][0]["when"] = [{"field": "order_channel", "op": "eq", "value": "web"}]
    result = validate_ai_authored_pack(
        pack, allowed_fields=frozenset({"order_channel", "canvas_hash"})
    )
    assert result["ok"] is True


def test_order_channel_rejected_without_allowed_fields_override():
    pack = _valid_pack()
    pack["rules"][0]["when"] = [{"field": "order_channel", "op": "eq", "value": "web"}]
    result = validate_ai_authored_pack(pack)
    assert result["ok"] is False
    assert any("unknown field" in e for e in result["errors"])


# --- unknown op rejected ---


def test_unknown_op_rejected():
    pack = _valid_pack()
    pack["rules"][0]["when"] = [{"field": "canvas_hash", "op": "regex", "value": ".*"}]
    result = validate_ai_authored_pack(pack)
    assert result["ok"] is False
    assert any("disallowed op" in e for e in result["errors"])


def test_between_op_rejected():
    pack = _valid_pack()
    pack["rules"][0]["when"] = [{"field": "amount", "op": "between", "value": [10, 100]}]
    result = validate_ai_authored_pack(pack)
    assert result["ok"] is False


# --- authored_by restrictions ---


def test_tarka_brand_in_authored_by_rejected():
    pack = _valid_pack()
    pack["authored_by"] = "tarka-model-v2"
    result = validate_ai_authored_pack(pack)
    assert result["ok"] is False


def test_saarthi_brand_in_authored_by_rejected():
    pack = _valid_pack()
    pack["authored_by"] = "Saarthi"
    result = validate_ai_authored_pack(pack)
    assert result["ok"] is False


def test_missing_authored_by_rejected():
    pack = _valid_pack()
    del pack["authored_by"]
    result = validate_ai_authored_pack(pack)
    assert result["ok"] is False


# --- multiple rules ---


def test_multiple_valid_rules():
    pack = _valid_pack()
    pack["rules"].append(
        {
            "id": "r2",
            "when": [{"field": "webgl_vendor", "op": "eq", "value": "NVIDIA"}],
            "score_delta": 15,
        }
    )
    result = validate_ai_authored_pack(pack)
    assert result["ok"] is True
    assert len(result["pack"]["rules"]) == 2


def test_too_many_rules_rejected():
    pack = _valid_pack()
    pack["rules"] = [
        {
            "id": f"r{i}",
            "when": [{"field": "canvas_hash", "op": "eq", "value": f"v{i}"}],
            "score_delta": 10,
        }
        for i in range(51)
    ]
    result = validate_ai_authored_pack(pack)
    assert result["ok"] is False


# --- event_type value validation ---


def test_unknown_event_type_value_rejected():
    pack = _valid_pack()
    pack["rules"][0]["when"] = [{"field": "event_type", "op": "eq", "value": "wire_transfer"}]
    result = validate_ai_authored_pack(pack)
    assert result["ok"] is False
    assert any("event_type" in e for e in result["errors"])


def test_valid_event_type_passes():
    pack = _valid_pack()
    pack["rules"][0]["when"] = [
        {"field": "event_type", "op": "eq", "value": "payment"},
        {"field": "canvas_hash", "op": "eq", "value": "abc"},
    ]
    result = validate_ai_authored_pack(pack)
    assert result["ok"] is True


# --- scout suggested_shadow_rule template validation ---


def test_scout_suggested_rule_valid():
    rule = {
        "id": "scout_canvas_hash_test_fp_val",
        "when": [{"op": "eq", "field": "canvas_hash", "value": "test_fp_value"}],
        "score_delta": 25.0,
        "metadata": {
            "is_shadow": True,
            "source": "scout_coordinated_burst",
            "fingerprint_kind": "canvas_hash",
        },
    }
    result = validate_suggested_shadow_rule_template(rule)
    assert result["ok"] is True, result.get("errors")


def test_scout_suggested_rule_webgl():
    rule = {
        "id": "scout_webgl_vendor_NVIDIACorpo",
        "when": [{"op": "eq", "field": "webgl_vendor", "value": "NVIDIA Corporation"}],
        "score_delta": 25.0,
        "metadata": {
            "is_shadow": True,
            "source": "scout_coordinated_burst",
            "fingerprint_kind": "webgl_vendor",
        },
    }
    result = validate_suggested_shadow_rule_template(rule)
    assert result["ok"] is True, result.get("errors")


# --- schema export ---


def test_json_schema_export():
    schema = ai_authored_pack_json_schema()
    assert isinstance(schema, dict)
    assert "properties" in schema


def test_build_llm_directive():
    directive = build_llm_directive()
    assert "AI Pack-Author Contract" in directive
    assert "JSON Schema" in directive
    assert '"shadow"' in directive


# --- all allowed fields are strings ---


def test_allowed_fields_are_strings():
    for f in ALLOWED_FIELDS:
        assert isinstance(f, str) and len(f) > 0


def test_allowed_ops_are_strings():
    for op in ALLOWED_OPS:
        assert isinstance(op, str) and len(op) > 0


# --- condition with empty when rejected ---


def test_rule_with_empty_when_rejected():
    pack = _valid_pack()
    pack["rules"][0]["when"] = []
    result = validate_ai_authored_pack(pack)
    assert result["ok"] is False


# --- version must be 1 ---


def test_version_2_rejected():
    pack = _valid_pack()
    pack["version"] = 2
    result = validate_ai_authored_pack(pack)
    assert result["ok"] is False


# --- SOP / OKF allowlist ---

_SOP = "Refunds above four hundred require a duty supervisor on the desk."
_OFF = "Unlisted desk rule: always deny new device logins from this tenant."


def _rich_report() -> dict:
    return {
        "report_id": "rpt-sop-1",
        "fingerprint_value": "abc123",
        "distinct_account_count": 4,
    }


def _allowlisted_chunk() -> dict:
    return {"id": "okf-1", "text": _SOP, "allowlisted": True}


class _RecordingLLM:
    def __init__(self, response):
        self._response = response
        self.calls = 0
        self.messages = None

    async def chat_json_validated(self, messages, *, model=None):
        self.calls += 1
        self.messages = messages
        return self._response


def test_unallowlisted_sop_text_is_rejected():
    pack = _valid_pack()
    pack["description"] = _OFF
    errors = sop_draft_errors(
        pack,
        [_allowlisted_chunk(), {"id": "x", "text": _OFF, "allowlisted": False}],
    )
    assert any("unallowlisted" in err for err in errors)


def test_sop_text_is_not_a_feature_or_score():
    pack = _valid_pack()
    pack["rules"][0]["when"] = [{"field": "canvas_hash", "op": "eq", "value": _SOP}]
    errors = sop_draft_errors(pack, [_allowlisted_chunk()])
    assert any("not a feature" in err for err in errors)
    pack["rules"][0]["when"] = [{"field": "canvas_hash", "op": "eq", "value": "abc123"}]
    pack["rules"][0]["score_delta"] = _SOP
    errors = sop_draft_errors(pack, [_allowlisted_chunk()])
    assert any("not a score" in err for err in errors)


def test_empty_and_thin_sop_do_not_draft():
    client = _RecordingLLM(_valid_pack())
    empty = asyncio.run(
        author_pack_from_hypothesis(_rich_report(), client, sop_chunks=[])
    )
    assert empty["ok"] is False
    assert empty["abstained"] is True
    assert "pack" not in empty
    assert "sop_missing" in empty["errors"]
    assert client.calls == 0

    thin = asyncio.run(
        author_pack_from_hypothesis(
            _rich_report(),
            client,
            sop_chunks=[{"id": "okf-1", "text": "too short", "allowlisted": True}],
        )
    )
    assert thin["ok"] is False
    assert "pack" not in thin
    assert client.calls == 0


def test_thin_evidence_abstains_before_model():
    client = _RecordingLLM(_valid_pack())
    result = asyncio.run(
        author_pack_from_hypothesis({}, client, sop_chunks=[_allowlisted_chunk()])
    )
    assert result["ok"] is False
    assert result["errors"] == ["thin_evidence"]
    assert "pack" not in result
    assert client.calls == 0
    assert evidence_is_thin({}) is True
    assert evidence_is_thin(_rich_report()) is False


def test_unallowlisted_text_is_not_sent_and_not_accepted():
    drafted = _valid_pack()
    drafted["description"] = _OFF
    client = _RecordingLLM(drafted)
    result = asyncio.run(
        author_pack_from_hypothesis(
            _rich_report(),
            client,
            sop_chunks=[
                _allowlisted_chunk(),
                {"id": "secret", "text": _OFF, "allowlisted": False},
            ],
        )
    )
    assert result["ok"] is False
    assert any("unallowlisted" in err for err in result["errors"])
    assert "pack" not in result
    blob = json.dumps(client.messages)
    assert _SOP in blob
    assert _OFF not in blob


def test_allowlisted_observe_draft_cites_ids_only():
    drafted = _valid_pack()
    drafted["evidence"] = {"sop_chunk_ids": ["okf-1"], "report_id": "rpt-sop-1"}
    client = _RecordingLLM(drafted)
    result = asyncio.run(
        author_pack_from_hypothesis(
            _rich_report(),
            client,
            sop_chunks=[_allowlisted_chunk()],
        )
    )
    assert result["ok"] is True
    assert result["pack"]["mode"] == "shadow"
    assert "promote" not in result["pack"]
    assert classify_sop_chunks(None)["state"] == "absent"


def test_missing_sop_stays_missing_on_the_same_in_vpc_call():
    drafted = _valid_pack()
    client = _RecordingLLM(drafted)
    result = asyncio.run(author_pack_from_hypothesis(_rich_report(), client))
    assert result["ok"] is True
    assert result["pack"]["mode"] == "shadow"
    assert "promote" not in result["pack"]
    assert client.calls == 1
    blob = json.dumps(client.messages)
    assert "Allowlisted tenant SOP" not in blob
    assert classify_sop_chunks(None)["state"] == "absent"
    assert classify_sop_chunks([])["state"] == "missing"
    contract = load_contract_text()
    assert "existing in-VPC" in contract
    assert "Empty or missing SOP stays missing" in contract
    assert "Do not Promote" in contract
    assert "ALLOW" in contract and "DENY" in contract


def test_llm_failure_does_not_echo_sop_text():
    class _Boom:
        async def chat_json_validated(self, messages, *, model=None):
            raise RuntimeError("upstream " + _SOP)

    result = asyncio.run(
        author_pack_from_hypothesis(
            _rich_report(),
            _Boom(),
            sop_chunks=[_allowlisted_chunk()],
        )
    )
    assert result["ok"] is False
    assert result["errors"] == ["llm_call_failed"]
    assert _SOP not in json.dumps(result)


def test_promote_and_allow_are_rejected():
    pack = _valid_pack()
    pack["promote"] = True
    assert any("forbidden field promote" in err for err in sop_draft_errors(pack, None))
    pack.pop("promote")
    pack["rules"][0]["decision"] = "ALLOW"
    assert any("forbidden" in err for err in sop_draft_errors(pack, None))
