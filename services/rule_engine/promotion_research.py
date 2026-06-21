"""Load ``services/research/simulator`` for promotion entity discovery (Prompt 200)."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

_RESEARCH_DIR = Path(__file__).resolve().parents[5] / "services" / "research"


def _ensure_research_path() -> None:
    path = str(_RESEARCH_DIR)
    if path not in sys.path:
        sys.path.insert(0, path)


def collect_matched_entity_ids_for_rule(
    rule: dict[str, Any],
    *,
    duckdb_path: str | None = None,
    lookback_days: int | None = None,
    duckdb_connection: Any | None = None,
) -> list[str]:
    _ensure_research_path()
    import simulator  # noqa: WPS433

    kwargs: dict[str, Any] = {}
    if duckdb_path is not None:
        kwargs["duckdb_path"] = duckdb_path
    if lookback_days is not None:
        kwargs["lookback_days"] = lookback_days
    if duckdb_connection is not None:
        kwargs["duckdb_connection"] = duckdb_connection
    return simulator.collect_matched_entity_ids(rule, **kwargs)
