"""Path B Hunt depth honesty (`tarka.hunt_depth/v1`). hunt_depth_max=1 until a tested AGE-safe fixed k exists."""

from __future__ import annotations

from typing import Any

HUNT_DEPTH_SCHEMA_ID = "tarka.hunt_depth/v1"
HUNT_DEPTH_MAX = 1
HUNT_DEPTH_CAPPED = "hunt:depth_capped"


def hunt_walk_depth(depth_requested: int) -> int:
    """Cap the actual AGE/Hunt walk. Never walk past hunt_depth_max."""
    try:
        requested = int(depth_requested)
    except (TypeError, ValueError):
        requested = HUNT_DEPTH_MAX
    return min(HUNT_DEPTH_MAX, max(1, requested))


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
    out = dict(data)
    out["schema_id"] = HUNT_DEPTH_SCHEMA_ID
    out["hunt_depth_max"] = HUNT_DEPTH_MAX
    out["depth_requested"] = requested
    out["depth_applied"] = applied
    out["degrade_reason"] = HUNT_DEPTH_CAPPED if requested > applied else None
    return out
