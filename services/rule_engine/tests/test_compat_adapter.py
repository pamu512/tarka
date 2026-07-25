"""Compat adapter maps decision-api evaluate → legacy rule_engine shape (no network)."""

from __future__ import annotations

from compat_adapter import (
    map_evaluate_to_legacy_rule_response,
    map_tx_payload_to_evaluate_body,
)


def test_map_tx_payload_includes_tenant_and_amount() -> None:
    body = map_tx_payload_to_evaluate_body(
        {
            "entity_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
            "amount": 42.5,
            "metadata": {"tenant_id": "t1", "user_id": "u1"},
        },
    )
    assert body["tenant_id"] == "t1"
    assert body["entity_id"] == "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    assert body["features"]["amount"] == 42.5
    assert body["features"]["user_id"] == "u1"


def test_map_evaluate_deny_to_block() -> None:
    out = map_evaluate_to_legacy_rule_response(
        {
            "decision": "deny",
            "score": 0.9,
            "trace_id": "tr-1",
            "rule_hits": ["rule-x"],
            "tags": [],
        },
        transaction_id="tx-1",
    )
    assert out["actions"] == ["BLOCK"]
    assert out["transaction_id"] == "tx-1"
    assert out["blocking_rule_id"] == "rule-x"
    assert out["compat"]["mode"] == "decision_api"


def test_map_evaluate_allow() -> None:
    out = map_evaluate_to_legacy_rule_response(
        {"decision": "allow", "score": 0.1, "tags": [], "rule_hits": []},
        transaction_id="tx-2",
    )
    assert out["actions"] == ["ALLOW"]
    assert out["blocking_rule_id"] is None
