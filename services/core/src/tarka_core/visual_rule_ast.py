"""Typed contracts for the visual rule JSON AST v1 (mirrors ``decision_api.rule_compiler_api``).

Uses :mod:`tarka_core.ast_definition` for ``custom_signal`` (same package; still no third-party deps).
Services should validate with Pydantic at the HTTP boundary.
"""

from __future__ import annotations

from typing import Any, TypedDict

from tarka_core.ast_definition import CustomSignalAstDict


class VisualAstLeafDict(TypedDict):
    op: str
    field: str
    value: Any


VisualAstWhenNodeDict = VisualAstLeafDict | CustomSignalAstDict


class VisualAstRuleDict(TypedDict, total=False):
    id: str
    all_of: list[VisualAstLeafDict]
    any_of: list[VisualAstLeafDict]
    tags: list[str]
    score_delta: float
    description: str


class VisualAstPackDict(TypedDict, total=False):
    name: str
    rules: list[VisualAstRuleDict]
    tag_rules: list[dict[str, Any]]
