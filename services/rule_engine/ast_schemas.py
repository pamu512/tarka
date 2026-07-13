"""Compatibility shim — AST schemas live in ``tarka_shared.ast_schemas``.

Prefer ``from tarka_shared.ast_schemas import Rule`` for new code.
"""

from __future__ import annotations

from tarka_shared.ast_schemas import (
    Action,
    AndNode,
    ConditionNode,
    FieldRef,
    LogicalNode,
    Operator,
    OrNode,
    Rule,
    ScalarLiteral,
    TransactionSchemaField,
    Value,
)

__all__ = [
    "Action",
    "AndNode",
    "ConditionNode",
    "FieldRef",
    "LogicalNode",
    "Operator",
    "OrNode",
    "Rule",
    "ScalarLiteral",
    "TransactionSchemaField",
    "Value",
]
