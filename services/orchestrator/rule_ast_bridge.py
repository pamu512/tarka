"""Bridge from the Python shadow-test AST (``tarka_shared.ast_schemas``) to the Rust
rule engine's strict JSON-AST twin (``tarka_rule_engine.evaluate_json_ast_strict``).

This is the S0 deliverable of the prune plan (v7 item 2.1): the parity harness in
``tests/test_rule_ast_parity.py`` pins that, for every tree the shadow-test route can
legally build, the mapped Rust evaluation equals ``rule_engine.evaluator.evaluate_node``.

Operator table (ConditionNode -> engine wire vocabulary; the parser stores ``op`` as
written, nothing normalizes it):

    EQ -> eq    NE -> not_eq    GT -> gt    LT -> lt    CONTAINS -> contains

Any other operator raises (gte/lte/in/not_in/starts_with/ends_with are engine-only and
have no ConditionNode counterpart).

Value mapping, per closed FieldRef field set (``entity_id, amount, timestamp,
metadata, country, graph_linked_to_blocked_count``):

- ``entity_id`` (UUID) -> canonical dashed string; EQ with a wire-form string RHS
  matches Python's ``_normalize_eq_rhs`` coercion for canonical forms.
- ``timestamp`` (datetime) -> epoch seconds (float), and an ISO-string RHS is parsed
  to epoch the same way ``_normalize_eq_rhs`` parses it (``Z`` tolerated). This keeps
  EQ, GT, and LT monotone; GT/LT string RHS is impossible because ``ConditionNode``
  rejects non-numeric/non-datetime literals for those operators.
- ``amount`` / ``graph_linked_to_blocked_count`` -> float, and numeric RHS literals
  normalize to float so ``100.0 == 100`` parity holds (serde_json treats them as
  unequal Values; Python does not).
- ``country`` (str | None) / ``metadata`` (dict) -> passed through as JSON values.

Known, documented divergence (pinned in the harness, not compensated): ``CONTAINS``
with a structured LHS stringifies differently (Python ``json.dumps`` uses ", " and
": " separators; the engine serializes compactly). Substrings that span a separator
match on one side only. The shadow-test contract only promises separator-insensitive
substrings (e.g. a quoted key token).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from ingestor.manifest_schema import TransactionSchema
from tarka_shared.ast_schemas import (
    AndNode,
    ConditionNode,
    LogicalNode,
    Operator,
    OrNode,
)

_CONDITION_OPERATOR_WIRE: dict[Operator, str] = {
    Operator.EQ: "eq",
    Operator.NE: "not_eq",
    Operator.GT: "gt",
    Operator.LT: "lt",
    Operator.CONTAINS: "contains",
}

SUPPORTED_FIELDS = (
    "entity_id",
    "amount",
    "timestamp",
    "metadata",
    "country",
    "graph_linked_to_blocked_count",
)

_EPOCH_UTC = datetime(1970, 1, 1, tzinfo=timezone.utc)


class RuleAstBridgeError(ValueError):
    """Raised when a tree cannot be mapped onto the strict JSON-AST twin."""


def _epoch_seconds(value: datetime) -> float:
    if value.tzinfo is None:
        # The transaction envelope carries UTC timestamps; treat naive as UTC.
        return (value - _EPOCH_UTC.replace(tzinfo=None)).total_seconds()
    return value.timestamp()


def _parse_iso_datetime(raw: str) -> datetime | None:
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


def _feature_value(field: str, raw: Any) -> Any:
    """Serialize one LHS field value into the engine's feature map."""
    if isinstance(raw, UUID):
        return str(raw)
    if isinstance(raw, datetime):
        return _epoch_seconds(raw)
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, (int, float)):
        return float(raw)
    return raw


def transaction_feature_map(
    transaction: TransactionSchema,
    graph_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Project the closed FieldRef field set of ``TransactionSchema`` into features.

    Mirrors ``rule_engine.evaluator._transaction_field_value`` exactly, including the
    ``graph_linked_to_blocked_count`` default of 0 when no graph context is supplied.
    """
    graph_count_raw = 0 if graph_context is None else graph_context.get("graph_linked_to_blocked_count", 0)
    try:
        graph_count = int(graph_count_raw)
    except (TypeError, ValueError):
        graph_count = 0
    return {
        "entity_id": _feature_value("entity_id", transaction.entity_id),
        "amount": _feature_value("amount", transaction.amount),
        "timestamp": _feature_value("timestamp", transaction.timestamp),
        "metadata": _feature_value("metadata", transaction.metadata),
        "country": _feature_value("country", transaction.country),
        "graph_linked_to_blocked_count": float(graph_count),
    }


def _rhs_value(field: str, rhs: Any) -> Any:
    """Convert a condition's RHS literal so it pairs with the mapped LHS field.

    Mirrors ``_normalize_eq_rhs`` for the timestamp wire-form coercion and normalizes
    numeric literals to float so int/float representation cannot split the engines.
    """
    if field == "timestamp":
        if isinstance(rhs, datetime):
            return _epoch_seconds(rhs)
        if isinstance(rhs, str):
            parsed = _parse_iso_datetime(rhs)
            return _epoch_seconds(parsed) if parsed is not None else rhs
        return rhs
    if field in ("amount", "graph_linked_to_blocked_count"):
        if isinstance(rhs, (int, float)) and not isinstance(rhs, bool):
            return float(rhs)
        return rhs
    return rhs


def logical_tree_to_json_ast(
    node: LogicalNode,
    features: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Translate a ``LogicalNode`` tree into the engine's strict JSON-AST shape.

    Leaf objects carry ``type, op, field, value``; composites carry ``type, children``;
    type strings are ``condition`` / ``and`` / ``or``. ``features`` (when given) supplies
    the mapped LHS so RHS literals can be paired to it.
    """
    if isinstance(node, ConditionNode):
        field = node.field.field
        if field not in SUPPORTED_FIELDS:
            raise RuleAstBridgeError(f"unsupported FieldRef field {field!r}")
        try:
            wire_op = _CONDITION_OPERATOR_WIRE[node.operator]
        except KeyError:
            raise RuleAstBridgeError(
                f"operator {node.operator!r} has no engine twin mapping",
            ) from None
        value = _rhs_value(field, node.value)
        return {"type": "condition", "op": wire_op, "field": field, "value": value}
    if isinstance(node, AndNode):
        if not node.children:
            raise RuleAstBridgeError("AndNode requires children")
        return {
            "type": "and",
            "children": [logical_tree_to_json_ast(child, features) for child in node.children],
        }
    if isinstance(node, OrNode):
        if not node.children:
            raise RuleAstBridgeError("OrNode requires children")
        return {
            "type": "or",
            "children": [logical_tree_to_json_ast(child, features) for child in node.children],
        }
    raise RuleAstBridgeError(f"unsupported AST node type: {type(node).__name__}")


def evaluate_shadow_tree_via_rust(
    node: LogicalNode,
    transaction: TransactionSchema,
    graph_context: dict[str, Any] | None = None,
) -> bool:
    """Evaluate a shadow-test tree on the Rust twin through this mapping.

    Raises ``RuntimeError`` when the engine module is unavailable (same contract the
    route's old lazy ``rule_engine`` import had) and ``RuleAstBridgeError`` for trees
    outside the mappable surface.
    """
    import json

    try:
        from tarka_rule_engine import evaluate_json_ast_strict
    except ImportError as exc:  # pragma: no cover — Docker / CI install the wheel
        raise RuntimeError("tarka_rule_engine is required for shadow tests") from exc

    features = transaction_feature_map(transaction, graph_context)
    ast_json = json.dumps(logical_tree_to_json_ast(node, features))
    features_json = json.dumps(features, default=str)
    return bool(evaluate_json_ast_strict(ast_json, features_json))
