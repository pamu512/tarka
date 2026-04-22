from __future__ import annotations

import datetime as dt
from typing import Any

"""Logical event time (business time) for Redis aggregates and replay alignment.

Velocity windows use ``AggregateStore.record_event(..., ts=...)``. When set, **event time**
replaces wall-clock ingest time for ZSET scores. See ``docs/docs/guides/late-arrival-watermarks.md``.
"""


def parse_event_time_to_unix(raw: Any) -> float | None:
    """Best-effort parse to Unix seconds. Returns None if missing or unparseable."""
    if raw is None:
        return None
    if isinstance(raw, bool):
        return None
    if isinstance(raw, (int, float)):
        f = float(raw)
        if f <= 0:
            return None
        if f > 1e12:
            f = f / 1000.0
        return f
    if isinstance(raw, str):
        s = raw.strip()
        if not s:
            return None
        try:
            return float(s)
        except ValueError:
            pass
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        try:
            ts = dt.datetime.fromisoformat(s)
        except ValueError:
            return None
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=dt.timezone.utc)
        return ts.timestamp()
    return None


_METADATA_KEYS = ("event_time", "event_ts", "occurred_at")
_PAYLOAD_KEYS = ("event_time", "event_ts", "occurred_at")


def event_time_unix_from_metadata(metadata: dict[str, Any] | None) -> float | None:
    if not isinstance(metadata, dict):
        return None
    for key in _METADATA_KEYS:
        if key in metadata:
            return parse_event_time_to_unix(metadata.get(key))
    return None


def event_time_unix_for_evaluate(
    metadata: dict[str, Any] | None,
    payload: dict[str, Any] | None,
) -> float | None:
    """Logical event time for ``record_event`` — metadata first, then payload keys."""
    t = event_time_unix_from_metadata(metadata)
    if t is not None:
        return t
    if not isinstance(payload, dict):
        return None
    for key in _PAYLOAD_KEYS:
        if key in payload:
            return parse_event_time_to_unix(payload.get(key))
    return None


def event_time_unix_from_payload_snapshot(snap: dict[str, Any] | None) -> float | None:
    """Prefer metadata event_time-style keys, then payload (audit export / replay)."""
    if not isinstance(snap, dict):
        return None
    meta = snap.get("metadata") if isinstance(snap.get("metadata"), dict) else None
    pl = snap.get("payload") if isinstance(snap.get("payload"), dict) else None
    return event_time_unix_for_evaluate(meta, pl)
