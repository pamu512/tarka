"""Evaluate a validated JSON AST node against a feature map (fail-closed on unknown shapes)."""

from __future__ import annotations

from typing import Any

from decision_api.ast_models import (
    JsonAstAnd,
    JsonAstCondition,
    JsonAstCustomSignal,
    JsonAstOr,
)
from decision_api.json_rules import _match_condition


def evaluate_json_ast(
    node: JsonAstCondition | JsonAstAnd | JsonAstOr | JsonAstCustomSignal,
    features: dict[str, Any],
) -> bool:
    if isinstance(node, JsonAstCustomSignal):
        # Values are injected upstream (Python merge); Rust treats this node as a no-op.
        return True
    if isinstance(node, JsonAstCondition):
        cond: dict[str, Any] = {"op": node.op, "field": node.field, "value": node.value}
        return _match_condition(features, cond)
    if isinstance(node, JsonAstAnd):
        return all(evaluate_json_ast(ch, features) for ch in node.children)
    if isinstance(node, JsonAstOr):
        return any(evaluate_json_ast(ch, features) for ch in node.children)
    return False
