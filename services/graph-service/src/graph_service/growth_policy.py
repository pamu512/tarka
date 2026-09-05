from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from typing import Any

from .graph_data_freshness import _parse_timestamp

ALLOWED_GROWTH_WINDOWS = ("5m", "1h", "6h", "24h", "7d")
DEFAULT_GROWTH_WINDOWS_RAW = "1h:5,24h:15"

_WINDOW_DELTAS = {
    "5m": timedelta(minutes=5),
    "1h": timedelta(hours=1),
    "6h": timedelta(hours=6),
    "24h": timedelta(hours=24),
    "7d": timedelta(days=7),
}


def _try_parse(raw: str | None) -> list[tuple[str, int]]:
    out: list[tuple[str, int]] = []
    for token in (raw or "").split(","):
        token = token.strip()
        if ":" not in token:
            continue
        window, _, thresh_s = token.partition(":")
        window = window.strip()
        if window not in ALLOWED_GROWTH_WINDOWS:
            continue
        try:
            thresh = int(thresh_s.strip())
        except ValueError:
            continue
        out.append((window, thresh))
    return out


def parse_growth_windows(raw: str | None) -> list[tuple[str, int]]:
    """Drop unknown tokens. Empty after parse → default pair."""
    parsed = _try_parse(raw)
    return parsed if parsed else _try_parse(DEFAULT_GROWTH_WINDOWS_RAW)


def window_to_timedelta(window: str) -> timedelta:
    return _WINDOW_DELTAS[window]


def count_growth(timestamps: list, window: str, *, now: datetime | None = None) -> int:
    """Untimestamped / unparsable stamps excluded."""
    delta = _WINDOW_DELTAS.get(window)
    if delta is None:
        return 0
    clock = now or datetime.now(UTC)
    if clock.tzinfo is None:
        clock = clock.replace(tzinfo=UTC)
    else:
        clock = clock.astimezone(UTC)
    n = 0
    for ts in timestamps:
        dt = _parse_timestamp(ts)
        if dt is None:
            continue
        if clock - dt <= delta:
            n += 1
    return n


def threshold_for(window: str, parsed: list[tuple[str, int]] | None = None) -> int | None:
    """1h → 5, 24h → 15 on default parse. Missing window → None."""
    pairs = (
        parsed
        if parsed is not None
        else parse_growth_windows(os.environ.get("GRAPH_GROWTH_WINDOWS"))
    )
    for w, thresh in pairs:
        if w == window:
            return thresh
    return None


def coalesce_edge_timestamp(properties: dict[str, Any] | None) -> Any:
    props = properties or {}
    for key in ("observed_at", "created_at", "updated_at"):
        val = props.get(key)
        if val is not None and str(val).strip():
            return val
    return None


def incident_edge_timestamps(entity_id: str, edges: list[Any]) -> list[Any]:
    stamps: list[Any] = []
    for edge in edges:
        if not isinstance(edge, dict):
            continue
        if entity_id not in (edge.get("from_id"), edge.get("to_id")):
            continue
        props = edge.get("properties") if isinstance(edge.get("properties"), dict) else {}
        stamps.append(coalesce_edge_timestamp(props))
    return stamps
