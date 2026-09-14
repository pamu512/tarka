"""Bitemporal as-of filtering over a rendered subgraph.

Pure post-filter (no store surgery): keeps edges consistent with the asked
moment — ``ingested_at`` (transaction time) <= as_of AND ``observed_at``
(valid time) <= as_of. Legacy edges carrying neither stamp are counted in
``unversioned_edges`` and kept: declared ambiguity beats silent loss.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any


def _parse_ts(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt


def _validate_as_of(as_of: str | None) -> datetime | None:
    """Parse ``as_of`` up front; raises ValueError on a non-timestamp before any store I/O."""
    if as_of is None:
        return None
    cutoff = _parse_ts(as_of)
    if cutoff is None:
        raise ValueError(f"invalid as_of timestamp: {as_of!r}")
    return cutoff


def apply_as_of(
    data: dict[str, Any],
    *,
    as_of: str | None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Filter edges to those visible at ``as_of``; pass through when ``as_of`` is None."""
    cutoff = _validate_as_of(as_of)
    if cutoff is None:
        return data
    del now  # reserved: clamping future as_of values once callers need it

    edges = [e for e in (data.get("edges") or []) if isinstance(e, dict)]
    kept: list[dict[str, Any]] = []
    unversioned = 0
    for edge in edges:
        props = edge.get("properties") if isinstance(edge.get("properties"), dict) else {}
        ingested = _parse_ts(props.get("ingested_at"))
        observed = _parse_ts(props.get("observed_at"))
        if ingested is None and observed is None:
            unversioned += 1
            kept.append(edge)
            continue
        if ingested is not None and ingested > cutoff:
            continue
        if observed is not None and observed > cutoff:
            continue
        kept.append(edge)

    return {**data, "edges": kept, "unversioned_edges": unversioned, "as_of": as_of}
