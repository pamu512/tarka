"""Unit tests for decision-api evaluate bridge (Approach A Phase 0)."""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

_SRC_ORCH = Path(__file__).resolve().parents[1]
if str(_SRC_ORCH) not in sys.path:
    sys.path.insert(0, str(_SRC_ORCH))

from decision_evaluate_bridge import (  # noqa: E402
    ACTION_MAP_V1,
    MissingTenantIdError,
    map_evaluate_to_actions,
    map_tx_to_evaluate_request,
    wire_rule_data_from_evaluate,
)


def _tx(**meta: object) -> SimpleNamespace:
    return SimpleNamespace(
        entity_id="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        amount=42.5,
        timestamp=datetime(2026, 7, 11, 12, 0, 0, tzinfo=timezone.utc),
        country="US",
        metadata=meta,
    )


def test_map_tx_requires_tenant() -> None:
    with pytest.raises(MissingTenantIdError):
        map_tx_to_evaluate_request(_tx(user_id="u1"))


def test_map_tx_tenant_from_header() -> None:
    body = map_tx_to_evaluate_request(_tx(), tenant_header="tenant-hdr")
    assert body["tenant_id"] == "tenant-hdr"
    assert body["event_type"] == "payment"
    assert body["entity_id"] == "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    assert body["payload"]["amount"] == 42.5
    assert body["payload"]["country"] == "US"


def test_map_tx_metadata_overrides() -> None:
    body = map_tx_to_evaluate_request(
        _tx(
            tenant_id="t1",
            event_type="login",
            session_id="sess-9",
            region="eu",
            device_id="dev-1",
            device_platform="ios",
            canvas_fingerprint="ab" * 32,
        ),
    )
    assert body["tenant_id"] == "t1"
    assert body["event_type"] == "login"
    assert body["session_id"] == "sess-9"
    assert body["region"] == "eu"
    assert body["device_context"]["device_id"] == "dev-1"
    assert body["device_context"]["platform"] == "ios"
    assert body["payload"]["canvas_fingerprint"] == "ab" * 32


@pytest.mark.parametrize(
    ("decision", "expected"),
    [
        ("deny", ["BLOCK"]),
        ("review", ["SHADOW_REVIEW", "FLAG"]),
        ("allow", ["ALLOW"]),
    ],
)
def test_map_evaluate_to_actions_table(decision: str, expected: list[str]) -> None:
    assert map_evaluate_to_actions({"decision": decision}) == expected


def test_map_evaluate_challenge_adds_flag() -> None:
    actions = map_evaluate_to_actions(
        {"decision": "allow", "recommended_action": "step_up_mfa"},
    )
    assert actions == ["ALLOW", "FLAG"]


def test_map_evaluate_deny_keeps_block_with_challenge() -> None:
    actions = map_evaluate_to_actions(
        {"decision": "deny", "recommended_action": "step_up_mfa"},
    )
    assert actions[0] == "BLOCK"
    assert "FLAG" in actions


def test_map_evaluate_shadow_tag() -> None:
    actions = map_evaluate_to_actions(
        {"decision": "allow", "tags": ["shadow_review"]},
    )
    assert "SHADOW_REVIEW" in actions


def test_wire_rule_data_block() -> None:
    rule_data = wire_rule_data_from_evaluate(
        {
            "trace_id": "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
            "decision": "deny",
            "score": 0.9,
            "tags": [],
            "rule_hits": ["rule-high-risk"],
            "recommended_action": "block",
        },
        transaction_id="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
    )
    assert rule_data["actions"] == ["BLOCK"]
    assert rule_data["blocking_rule_id"] == "rule-high-risk"
    assert rule_data["decision"] == "DENY"
    assert rule_data["scores"]["policy"] == 0.9
    assert rule_data["evaluation_trace"][0]["action_map"] == ACTION_MAP_V1
    assert any(r.get("rule_id") == "rule-high-risk" for r in rule_data["evaluation_trace"])


def test_wire_rule_data_deny_without_hits() -> None:
    rule_data = wire_rule_data_from_evaluate(
        {"decision": "deny", "score": 1.0, "tags": [], "rule_hits": []},
        transaction_id="tid",
    )
    assert rule_data["blocking_rule_id"] == "decision_api_deny"


def test_compare_rule_eval_outcomes_match_and_mismatch() -> None:
    from decision_evaluate_bridge import compare_rule_eval_outcomes

    match = compare_rule_eval_outcomes(
        decision_api_rule_data={"actions": ["ALLOW"], "blocking_rule_id": None},
        python_rule_data={"actions": ["ALLOW"], "blocking_rule_id": None},
    )
    assert match["actions_match"] is True
    assert match["blocking_rule_id_match"] is True

    mismatch = compare_rule_eval_outcomes(
        decision_api_rule_data={"actions": ["BLOCK"], "blocking_rule_id": "r1"},
        python_rule_data={"actions": ["ALLOW"], "blocking_rule_id": None},
    )
    assert mismatch["actions_match"] is False
    assert mismatch["blocking_rule_id_match"] is False
    assert mismatch["decision_api_actions"] == ["BLOCK"]
    assert mismatch["python_actions"] == ["ALLOW"]
