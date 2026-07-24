"""Pick a single ISO-8601 freshness timestamp from graph vertex property candidates."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any


def _parse_timestamp(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt.astimezone(UTC)
    if hasattr(value, "to_native"):
        try:
            native = value.to_native()
            if isinstance(native, datetime):
                dt = native
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=UTC)
                return dt.astimezone(UTC)
        except Exception:
            return None
    text = str(value).strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def graph_data_as_of_iso(props: dict[str, Any] | None) -> str | None:
    """Latest known graph write time for an entity (UTC ISO-8601 with ``Z`` suffix)."""
    if not props:
        return None
    best: datetime | None = None
    for key in ("updated_at", "last_seen", "tags_updated_at", "observed_at"):
        dt = _parse_timestamp(props.get(key))
        if dt is None:
            continue
        if best is None or dt > best:
            best = dt
    if best is None:
        return None
    return best.isoformat().replace("+00:00", "Z")
