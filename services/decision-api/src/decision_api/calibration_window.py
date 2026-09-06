from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

SCHEMA_ID = "tarka.calibration_window/v1"
WINDOW_BLOCKERS = frozenset({"window_open", "thin_labels", "fp_above_cap"})


def _env_int(name: str, default: int) -> int:
    raw = (os.environ.get(name) or "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    raw = (os.environ.get(name) or "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def resolve_window_limits() -> tuple[int, int, float]:
    return (
        max(0, _env_int("TARKA_CALIBRATION_MIN_DAYS", 7)),
        max(0, _env_int("TARKA_CALIBRATION_MIN_LABELS", 20)),
        max(0.0, _env_float("TARKA_CALIBRATION_MAX_FP", 0.05)),
    )


def calibration_window(
    *,
    first_label_at: datetime | None,
    label_count: int,
    fp_rate: float | None,
    now: datetime | None = None,
    min_days: int | None = None,
    min_labels: int | None = None,
    max_fp: float | None = None,
) -> dict[str, Any]:
    days_lim, labels_lim, fp_lim = resolve_window_limits()
    if min_days is not None:
        days_lim = max(0, int(min_days))
    if min_labels is not None:
        labels_lim = max(0, int(min_labels))
    if max_fp is not None:
        fp_lim = max(0.0, float(max_fp))
    now_ts = now or datetime.now(timezone.utc)
    if now_ts.tzinfo is None:
        now_ts = now_ts.replace(tzinfo=timezone.utc)
    first = first_label_at
    if first is not None and first.tzinfo is None:
        first = first.replace(tzinfo=timezone.utc)

    blockers: list[str] = []
    days = 0
    if first is None:
        if days_lim > 0:
            blockers.append("window_open")
    else:
        days = max(0, (now_ts - first).days)
        if days < days_lim:
            blockers.append("window_open")
    try:
        n_labels = int(label_count)
    except (TypeError, ValueError):
        n_labels = 0
    if n_labels < labels_lim:
        blockers.append("thin_labels")
    if fp_rate is not None:
        try:
            rate = float(fp_rate)
        except (TypeError, ValueError):
            rate = None
        else:
            if rate > fp_lim:
                blockers.append("fp_above_cap")
            fp_rate = rate
    return {
        "schema_id": SCHEMA_ID,
        "ok": not blockers,
        "promote_allowed": not blockers,
        "blockers": blockers,
        "min_days": days_lim,
        "min_labels": labels_lim,
        "max_fp": fp_lim,
        "days": days,
        "label_count": n_labels,
        "fp_rate": fp_rate,
    }


def can_override_calibration_window(roles: Sequence[str], reason: str) -> bool:
    if len((reason or "").strip()) < 8:
        return False
    have = {str(r).strip() for r in roles}
    return "RiskArchitect" in have or "admin" in have


def apply_window_override(
    desk: Mapping[str, Any],
    window: Mapping[str, Any],
    *,
    reason: str,
    roles: Sequence[str],
) -> tuple[dict[str, Any], bool]:
    """Drop window blockers when RiskArchitect/admin gives a reason. Other gates stay."""
    out = dict(desk)
    out["blockers"] = [str(b) for b in (desk.get("blockers") or [])]
    if window.get("ok"):
        return out, False
    if not can_override_calibration_window(roles, reason):
        return out, False
    remaining = [b for b in out["blockers"] if b not in WINDOW_BLOCKERS]
    out["blockers"] = remaining
    out["promote_allowed"] = len(remaining) == 0
    out["calibration_override"] = True
    return out, True
