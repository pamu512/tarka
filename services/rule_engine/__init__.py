"""Rule engine: AST schemas and (future) evaluation."""

from typing import Any

from .ast_schemas import (
    Action,
    AndNode,
    ConditionNode,
    FieldRef,
    LogicalNode,
    Operator,
    OrNode,
    Rule,
    Value,
)

__all__ = [
    "Action",
    "AndNode",
    "ConditionNode",
    "evaluate_node",
    "evaluate_ruleset",
    "FieldRef",
    "LogicalNode",
    "Operator",
    "OrNode",
    "Rule",
    "Value",
]


def __getattr__(name: str) -> Any:
    """Lazy import so ``import rule_engine`` does not require ``ingestor`` until evaluation is used."""
    if name == "evaluate_node":
        from .evaluator import evaluate_node as _evaluate_node

        return _evaluate_node
    if name == "evaluate_ruleset":
        from .evaluator import evaluate_ruleset as _evaluate_ruleset

        return _evaluate_ruleset
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
