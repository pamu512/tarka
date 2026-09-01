"""Tarka rule engine: PyO3 LFFI with panic-safe :class:`RuleEngine` wrapper."""

from __future__ import annotations

from typing import Any

from tarka_rule_engine._native import (  # noqa: F401
    ASTValidationError,
    EvaluationBudgetExceeded,
    JsonAstMalformedError,
    JsonEngineError,
    RegexCompilationError,
    RuleEnginePanic,
    evaluate_adhoc_packs_rust,
    evaluate_json_ast_strict,
    evaluate_json_rules_rust,
    rust_engine_cache_stats,
    sync_packs_json,
    validate_json_rule_ast,
)
from tarka_rule_engine._wrapper import (
    PANIC_TEST_VELOCITY_SENTINEL,
    EvaluationContext,
    RuleEngine,
)

__all__ = [
    "ASTValidationError",
    "EvaluationBudgetExceeded",
    "EvaluationContext",
    "JsonAstMalformedError",
    "JsonEngineError",
    "PANIC_TEST_VELOCITY_SENTINEL",
    "RegexCompilationError",
    "RuleEngine",
    "RuleEnginePanic",
    "create_evaluate_app",
    "evaluate_adhoc_packs_rust",
    "evaluate_json_ast_strict",
    "evaluate_json_rules_rust",
    "rust_engine_cache_stats",
    "sync_packs_json",
    "validate_json_rule_ast",
]


def create_evaluate_app() -> Any:
    """ASGI app exposing ``POST /v1/evaluate`` (panic-safe via :class:`RuleEngine`)."""
    from tarka_rule_engine.http_api import create_evaluate_app as _create

    return _create()
