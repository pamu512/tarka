"""
Analyst hypothesis safety gate (Prompt 196).

Re-exports :func:`simulator.validate_hypothesis_backtest` for CLI and services.
"""

from __future__ import annotations

from simulator import (  # noqa: F401
    BacktestValidation,
    MAX_ANALYST_SUGGESTION_FALSE_POSITIVE_RATE,
    compute_false_positive_rate,
    validate_hypothesis_backtest,
)

__all__ = [
    "BacktestValidation",
    "MAX_ANALYST_SUGGESTION_FALSE_POSITIVE_RATE",
    "compute_false_positive_rate",
    "validate_hypothesis_backtest",
]
