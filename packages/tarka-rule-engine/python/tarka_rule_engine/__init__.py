"""Tarka rule engine: PyO3 LFFI with panic-safe :class:`RuleEngine` wrapper."""

from __future__ import annotations

from typing import Any

from tarka_rule_engine._wrapper import (
    PANIC_TEST_VELOCITY_SENTINEL,
    EvaluationContext,
    RuleEngine,
)

__all__ = [
    "EvaluationContext",
    "PANIC_TEST_VELOCITY_SENTINEL",
    "RuleEngine",
    "create_evaluate_app",
]


def create_evaluate_app() -> Any:
    """ASGI app exposing ``POST /v1/evaluate`` (panic-safe via :class:`RuleEngine`)."""
    from tarka_rule_engine.http_api import create_evaluate_app as _create

    return _create()
