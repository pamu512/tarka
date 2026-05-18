"""Tests for :mod:`rule_engine.evaluator`."""

from __future__ import annotations

import sys
from typing import Any
from datetime import UTC, datetime
from pathlib import Path
from unittest import mock
from uuid import UUID

_SRC_RULE = Path(__file__).resolve().parents[1] / "src"
_SRC_INGESTOR = Path(__file__).resolve().parents[2] / "ingestor" / "src"
for _p in (_SRC_RULE, _SRC_INGESTOR):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from ingestor.manifest_schema import TransactionSchema  # noqa: E402
from rule_engine import evaluator as evaluator_module  # noqa: E402
from rule_engine.ast_schemas import (  # noqa: E402
    Action,
    AndNode,
    ConditionNode,
    FieldRef,
    Operator,
    OrNode,
    Rule,
)
from rule_engine.evaluator import evaluate_node, evaluate_ruleset, evaluate_ruleset_detailed  # noqa: E402


def test_evaluate_condition_amount_gt_returns_true_when_amount_exceeds_threshold() -> None:
    """Gate: ``amount > 100`` is true when transaction amount is 150."""
    node = ConditionNode(
        field=FieldRef(field="amount"),
        operator=Operator.GT,
        value=100,
    )
    tx = TransactionSchema(
        entity_id=UUID("11111111-1111-1111-1111-111111111111"),
        amount=150.0,
        timestamp=datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC),
        metadata={},
    )
    assert evaluate_node(node, tx) is True


def test_evaluate_condition_amount_gt_returns_false_when_below() -> None:
    node = ConditionNode(
        field=FieldRef(field="amount"),
        operator=Operator.GT,
        value=100,
    )
    tx = TransactionSchema(
        entity_id=UUID("22222222-2222-2222-2222-222222222222"),
        amount=50.0,
        timestamp=datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC),
        metadata={},
    )
    assert evaluate_node(node, tx) is False


def test_and_node_short_circuits_first_false_skips_later_children() -> None:
    """Gate: first conjunct false → remaining children are not evaluated (no crash from second)."""
    tx = TransactionSchema(
        entity_id=UUID("44444444-4444-4444-4444-444444444444"),
        amount=1.0,
        timestamp=datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC),
        metadata={},
    )
    first = ConditionNode(
        field=FieldRef(field="amount"),
        operator=Operator.GT,
        value=999.0,
    )
    second = ConditionNode(
        field=FieldRef(field="amount"),
        operator=Operator.GT,
        value=0.0,
    )
    node = AndNode(children=[first, second])

    calls: list[int] = []

    def _condition_side_effect(
        n: ConditionNode,
        t: TransactionSchema,
        graph_context: dict[str, Any] | None = None,
    ) -> bool:
        _ = graph_context
        calls.append(1)
        if len(calls) == 1:
            return False
        raise RuntimeError("second conjunct must not be evaluated")

    with mock.patch.object(
        evaluator_module, "_evaluate_condition", side_effect=_condition_side_effect
    ):
        assert evaluate_node(node, tx) is False

    assert len(calls) == 1


def test_or_node_short_circuits_first_true_skips_later_children() -> None:
    tx = TransactionSchema(
        entity_id=UUID("55555555-5555-5555-5555-555555555555"),
        amount=50.0,
        timestamp=datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC),
        metadata={},
    )
    first = ConditionNode(
        field=FieldRef(field="amount"),
        operator=Operator.GT,
        value=10.0,
    )
    second = ConditionNode(
        field=FieldRef(field="amount"),
        operator=Operator.GT,
        value=0.0,
    )
    node = OrNode(children=[first, second])

    calls: list[int] = []

    def _condition_side_effect(
        n: ConditionNode,
        t: TransactionSchema,
        graph_context: dict[str, Any] | None = None,
    ) -> bool:
        _ = graph_context
        calls.append(1)
        if len(calls) == 1:
            return True
        raise RuntimeError("second disjunct must not be evaluated")

    with mock.patch.object(
        evaluator_module, "_evaluate_condition", side_effect=_condition_side_effect
    ):
        assert evaluate_node(node, tx) is True

    assert len(calls) == 1


def test_evaluate_ruleset_block_from_middle_priority_skips_lower_priority() -> None:
    """Gate: BLOCK on middle-priority rule returns ``[BLOCK]``; lowest-priority root is never evaluated."""
    tx = TransactionSchema(
        entity_id=UUID("66666666-6666-6666-6666-666666666666"),
        amount=75.0,
        timestamp=datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC),
        metadata={},
    )
    always_true = ConditionNode(
        field=FieldRef(field="amount"),
        operator=Operator.GT,
        value=0.0,
    )
    never_matches = ConditionNode(
        field=FieldRef(field="amount"),
        operator=Operator.GT,
        value=10_000.0,
    )
    block_match = ConditionNode(
        field=FieldRef(field="amount"),
        operator=Operator.GT,
        value=50.0,
    )
    r_high = Rule(
        id=UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"),
        name="high",
        root_node=never_matches,
        action=Action.FLAG,
        priority=10,
    )
    r_mid = Rule(
        id=UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"),
        name="mid",
        root_node=block_match,
        action=Action.BLOCK,
        priority=20,
    )
    r_low = Rule(
        id=UUID("cccccccc-cccc-cccc-cccc-cccccccccccc"),
        name="low",
        root_node=always_true,
        action=Action.ALLOW,
        priority=30,
    )
    shuffled = [r_mid, r_low, r_high]

    with mock.patch.object(
        evaluator_module,
        "evaluate_node",
        wraps=evaluator_module.evaluate_node,
    ) as ev_mock:
        out = evaluate_ruleset(shuffled, tx)

    assert out == [Action.BLOCK]
    assert ev_mock.call_count == 2

    detail = evaluate_ruleset_detailed(shuffled, tx)
    assert detail.actions == [Action.BLOCK]
    assert detail.blocking_rule_id == "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
    assert len(detail.trace) == 2
    assert detail.trace[0]["priority"] == 10
    assert detail.trace[0]["matched"] is False
    assert detail.trace[1]["rule_id"] == "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
    assert detail.trace[1]["matched"] is True


def test_evaluate_country_ne_true_when_differs_from_literal() -> None:
    node = ConditionNode(
        field=FieldRef(field="country"),
        operator=Operator.NE,
        value="US",
    )
    tx = TransactionSchema(
        entity_id=UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"),
        amount=10.0,
        timestamp=datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC),
        metadata={},
        country="CA",
    )
    assert evaluate_node(node, tx) is True


def test_evaluate_country_ne_false_when_matches_literal() -> None:
    node = ConditionNode(
        field=FieldRef(field="country"),
        operator=Operator.NE,
        value="US",
    )
    tx = TransactionSchema(
        entity_id=UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"),
        amount=10.0,
        timestamp=datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC),
        metadata={},
        country="US",
    )
    assert evaluate_node(node, tx) is False


def test_graph_linked_to_blocked_count_uses_injected_context() -> None:
    """Gate: GRAPH_LINKED_TO_BLOCKED_COUNT compares against evaluator graph_context."""
    node = ConditionNode(
        field=FieldRef(field="graph_linked_to_blocked_count"),
        operator=Operator.GT,
        value=0,
    )
    tx = TransactionSchema(
        entity_id=UUID("99999999-9999-9999-9999-999999999999"),
        amount=150.0,
        timestamp=datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC),
        metadata={"user_id": "u1", "ip": "10.0.0.1"},
    )
    assert evaluate_node(node, tx, None) is False
    assert evaluate_node(node, tx, {"graph_linked_to_blocked_count": 0}) is False
    assert evaluate_node(node, tx, {"graph_linked_to_blocked_count": 1}) is True


def test_evaluate_eq_uses_operator_eq() -> None:
    node = ConditionNode(
        field=FieldRef(field="amount"),
        operator=Operator.EQ,
        value=42.0,
    )
    tx = TransactionSchema(
        entity_id=UUID("33333333-3333-3333-3333-333333333333"),
        amount=42.0,
        timestamp=datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC),
        metadata={},
    )
    assert evaluate_node(node, tx) is True
