"""Typed contracts for the visual rule JSON AST v1 (mirrors ``decision_api.rule_compiler_api``).

This module is **stdlib-only** so ``tarka_core`` stays free of optional heavy deps; services
should still validate with Pydantic at the HTTP boundary.
"""

from __future__ import annotations

from typing import Any, TypedDict


class VisualAstLeafDict(TypedDict):
    op: str
    field: str
    value: Any


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
