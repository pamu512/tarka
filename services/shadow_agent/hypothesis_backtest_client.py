"""Load ``services/research/simulator`` for Prompt 196 hypothesis backtest gating."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

_RESEARCH_DIR = Path(__file__).resolve().parents[5] / "services" / "research"


def _ensure_research_path() -> None:
    path = str(_RESEARCH_DIR)
    if path not in sys.path:
        sys.path.insert(0, path)


def validate_suggested_rule_for_analyst(
    rule: dict[str, Any],
    *,
    duckdb_path: str | None = None,
    postgres_url: str | None = None,
    labels: Any | None = None,
    duckdb_connection: Any | None = None,
    lookback_days: int | None = None,
    max_false_positive_rate: float | None = None,
) -> dict[str, Any]:
    """Run DuckDB 7-day backtest; return validation dict with ``analyst_suggestion_allowed``."""
    _ensure_research_path()
    import simulator  # noqa: WPS433

    kwargs: dict[str, Any] = {}
    if duckdb_path is not None:
        kwargs["duckdb_path"] = duckdb_path
    if postgres_url is not None:
        kwargs["postgres_url"] = postgres_url
    if labels is not None:
        kwargs["labels"] = labels
    if duckdb_connection is not None:
        kwargs["duckdb_connection"] = duckdb_connection
    if lookback_days is not None:
        kwargs["lookback_days"] = lookback_days
    if max_false_positive_rate is not None:
        kwargs["max_false_positive_rate"] = max_false_positive_rate

    result = simulator.validate_hypothesis_backtest(rule, **kwargs)
    return result.as_dict()


def build_block_overlay_timeseries_for_rule(
    rule: dict[str, Any],
    *,
    duckdb_path: str | None = None,
    duckdb_connection: Any | None = None,
    lookback_days: int | None = None,
) -> list[dict[str, Any]]:
    """Hourly production vs shadow block counts for Recharts overlay (Prompt 198)."""
    _ensure_research_path()
    import simulator  # noqa: WPS433

    kwargs: dict[str, Any] = {}
    if duckdb_path is not None:
        kwargs["duckdb_path"] = duckdb_path
    if duckdb_connection is not None:
        kwargs["duckdb_connection"] = duckdb_connection
    if lookback_days is not None:
        kwargs["lookback_days"] = lookback_days
    return simulator.build_block_overlay_timeseries(rule, **kwargs)
