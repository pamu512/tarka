"""One computed velocity assist. Not a Redis key."""

from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger(__name__)

COMPUTED_NAME = "event_count_1h_share_24h"
DEFAULT_WARMUP_24H = 10
COMPUTED_EXPLANATION = (
    "event_count_1h / event_count_24h after 24h warmup; omitted when history is thin"
)

_warmup_bad_logged = False


def resolve_warmup_24h(raw: str | None) -> int:
    """Parse TARKA_BASELINE_WARMUP_24H. Garbage → 10 (log once). <1 → 1."""
    global _warmup_bad_logged
    if raw is None or not str(raw).strip():
        return DEFAULT_WARMUP_24H
    try:
        n = int(str(raw).strip())
    except (TypeError, ValueError):
        if not _warmup_bad_logged:
            log.warning(
                "TARKA_BASELINE_WARMUP_24H invalid %r; using %s",
                raw,
                DEFAULT_WARMUP_24H,
            )
            _warmup_bad_logged = True
        return DEFAULT_WARMUP_24H
    return n if n >= 1 else 1


def _as_number(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def apply_count_share(features: dict, warmup: int) -> None:
    """Set or delete COMPUTED_NAME. Never writes rate / baseline_ratio."""
    features.pop(COMPUTED_NAME, None)
    day = _as_number(features.get("event_count_24h"))
    if day is None or day < max(int(warmup), 1):
        return
    hour = _as_number(features.get("event_count_1h"))
    if hour is None:
        hour = 0.0
    features[COMPUTED_NAME] = hour / day
