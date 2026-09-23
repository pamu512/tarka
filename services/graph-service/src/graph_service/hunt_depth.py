"""Path B Hunt depth honesty (`tarka.hunt_depth/v1`).

Default: hunt_depth_max=1 (depth-2 walk is opt-in via HUNT_DEPTH_2_ENABLED and
tops out at an explicit fixed 2-edge pattern — AGE 1.6 has no variable-length
paths, so depth-2 is a second explicit hop, never `[*1..n]`).
"""

from __future__ import annotations

import os
from typing import Any

HUNT_DEPTH_SCHEMA_ID = "tarka.hunt_depth/v1"
HUNT_DEPTH_MAX = 1
HUNT_DEPTH_CAPPED = "hunt:depth_capped"


def depth_2_enabled() -> bool:
    raw = (os.environ.get("HUNT_DEPTH_2_ENABLED") or "").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def hunt_walk_depth(depth_requested: int) -> int:
    """Cap the actual AGE/Hunt walk. Never walk past the effective max."""
    ceiling = 2 if depth_2_enabled() else HUNT_DEPTH_MAX
    try:
        requested = int(depth_requested)
    except (TypeError, ValueError):
        requested = HUNT_DEPTH_MAX
    return min(ceiling, max(1, requested))


def attach_hunt_depth(
    data: dict[str, Any],
    depth_requested: int,
    *,
    depth_applied: int,
) -> dict[str, Any]:
    try:
        requested = int(depth_requested)
    except (TypeError, ValueError):
        requested = HUNT_DEPTH_MAX
    applied = int(depth_applied)
    ceiling = 2 if depth_2_enabled() else HUNT_DEPTH_MAX
    out = dict(data)
    out["schema_id"] = HUNT_DEPTH_SCHEMA_ID
    out["hunt_depth_max"] = HUNT_DEPTH_MAX
    out["hunt_depth_ceiling"] = ceiling
    out["depth_requested"] = requested
    out["depth_applied"] = applied
    out["degrade_reason"] = HUNT_DEPTH_CAPPED if requested > applied else None
    return out
