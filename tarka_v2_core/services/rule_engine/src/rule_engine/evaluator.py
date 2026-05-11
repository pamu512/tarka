"""Recursive evaluation of rule AST nodes against a transaction envelope.

Uses :mod:`operator` for comparisons (no ``eval``). Requires ``ingestor`` on ``PYTHONPATH``.
"""

from __future__ import annotations

import json
import operator
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from ingestor.manifest_schema import TransactionSchema

from rule_engine.ast_schemas import (
    Action,
    AndNode,
    ConditionNode,
    LogicalNode,
    Operator,
    OrNode,
    Rule,
)

_OPERATOR_FUNCS: dict[Operator, Any] = {
    Operator.EQ: operator.eq,
    Operator.NE: operator.ne,
    Operator.GT: operator.gt,
    Operator.LT: operator.lt,
}


def _transaction_field_value(
    transaction: TransactionSchema,
    field_name: str,
    graph_context: dict[str, Any] | None,
) -> Any:
    if field_name == "entity_id":
        return transaction.entity_id
    if field_name == "amount":
        return transaction.amount
    if field_name == "timestamp":
        return transaction.timestamp
    if field_name == "metadata":
        return transaction.metadata
    if field_name == "country":
        return transaction.country
    if field_name == "graph_linked_to_blocked_count":
        if graph_context is None:
            return 0
        raw = graph_context.get("graph_linked_to_blocked_count", 0)
        try:
            return int(raw)
        except (TypeError, ValueError):
            return 0
    raise ValueError(f"unsupported FieldRef field {field_name!r}")


def _normalize_eq_rhs(lhs: Any, rhs: Any) -> Any:
    """Align RHS with LHS for equality (e.g. UUID vs string wire forms)."""
    if isinstance(lhs, UUID) and isinstance(rhs, str):
        try:
            return UUID(rhs)
        except ValueError:
            return rhs
    if isinstance(lhs, datetime) and isinstance(rhs, str):
        try:
            return datetime.fromisoformat(rhs.replace("Z", "+00:00"))
        except ValueError:
            return rhs
    return rhs


def _evaluate_contains(lhs: Any, rhs: str) -> bool:
    if isinstance(lhs, str):
        return operator.contains(lhs, rhs)
    if isinstance(lhs, dict):
        return operator.contains(json.dumps(lhs, sort_keys=True, default=str), rhs)
    if isinstance(lhs, list):
        return operator.contains(json.dumps(lhs, default=str), rhs)
    return operator.contains(str(lhs), rhs)


def _evaluate_condition(
    node: ConditionNode,
    transaction: TransactionSchema,
    graph_context: dict[str, Any] | None,
) -> bool:
    lhs = _transaction_field_value(transaction, node.field.field, graph_context)
    rhs = node.value
    op = node.operator

    if op == Operator.CONTAINS:
        if not isinstance(rhs, str):
            return False
        return _evaluate_contains(lhs, rhs)

    fn = _OPERATOR_FUNCS.get(op)
    if fn is None:
        raise TypeError(f"unsupported operator for evaluation: {op!r}")

    rhs_adj = (
        _normalize_eq_rhs(lhs, rhs) if op in (Operator.EQ, Operator.NE) else rhs
    )
    try:
        return bool(fn(lhs, rhs_adj))
    except TypeError:
        return False


def evaluate_node(
    node: LogicalNode,
    transaction: TransactionSchema,
    graph_context: dict[str, Any] | None = None,
) -> bool:
    """
    Recursively evaluate a logical AST node against ``transaction``.

    ``ConditionNode`` uses :mod:`operator` mappings (``eq``, ``gt``, ``lt``); ``CONTAINS`` uses
    ``operator.contains`` on strings or JSON-serialized structured fields.

    ``AndNode`` / ``OrNode`` use **short-circuit** evaluation: ``AndNode`` stops at the first
    false child; ``OrNode`` stops at the first true child (remaining siblings are not evaluated).
    """
    if isinstance(node, ConditionNode):
        return _evaluate_condition(node, transaction, graph_context)
    if isinstance(node, AndNode):
        return all(evaluate_node(child, transaction, graph_context) for child in node.children)
    if isinstance(node, OrNode):
        return any(evaluate_node(child, transaction, graph_context) for child in node.children)
    raise TypeError(f"unsupported AST node type: {type(node).__name__}")


@dataclass(frozen=True)
class RulesetEvaluation:
    """Outcome of :func:`evaluate_ruleset_detailed` including per-rule evaluation trace."""

    actions: list[Action]
    trace: list[dict[str, Any]]
    blocking_rule_id: str | None


def evaluate_ruleset_detailed(
    rules: Sequence[Rule],
    transaction: TransactionSchema,
    graph_context: dict[str, Any] | None = None,
) -> RulesetEvaluation:
    """
    Evaluate ``rules`` in ascending ``priority`` order (lower integer runs first).

    Builds an execution trace entry for every rule in evaluation order. When a rule matches,
    its action is recorded on the trace row. If any matching rule yields :attr:`Action.BLOCK`,
    evaluation stops immediately; :attr:`RulesetEvaluation.actions` is exactly ``[Action.BLOCK]``
    and :attr:`RulesetEvaluation.blocking_rule_id` is that rule's id string.
    """
    ordered = sorted(rules, key=lambda r: r.priority)
    results: list[Action] = []
    trace: list[dict[str, Any]] = []
    for rule in ordered:
        matched = evaluate_node(rule.root_node, transaction, graph_context)
        row: dict[str, Any] = {
            "rule_id": str(rule.id),
            "rule_name": rule.name,
            "priority": rule.priority,
            "matched": matched,
        }
        if matched:
            row["action"] = rule.action.value
        trace.append(row)
        if matched:
            if rule.action == Action.BLOCK:
                return RulesetEvaluation(
                    [Action.BLOCK],
                    trace,
                    str(rule.id),
                )
            results.append(rule.action)
    return RulesetEvaluation(results, trace, None)


def evaluate_ruleset(
    rules: Sequence[Rule],
    transaction: TransactionSchema,
    graph_context: dict[str, Any] | None = None,
) -> list[Action]:
    """
    Evaluate ``rules`` in ascending ``priority`` order (lower integer runs first).

    For each rule whose ``root_node`` matches the transaction, its ``action`` is collected.
    If any matching rule yields :attr:`Action.BLOCK`, evaluation stops immediately and the
    result is exactly ``[Action.BLOCK]`` (prior collected actions from this invocation are discarded).
    """
    return evaluate_ruleset_detailed(rules, transaction, graph_context).actions
