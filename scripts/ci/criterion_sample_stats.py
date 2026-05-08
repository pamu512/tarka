"""Shared helpers: read Criterion ``sample.json`` and compute expanded per-iteration p99 (ns)."""

from __future__ import annotations

import json
import math
from pathlib import Path


def load_sample(path: Path) -> tuple[list[float], list[float]]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    try:
        times = raw["times"]
        iters = raw["iters"]
    except KeyError as e:
        raise ValueError(f"{path}: missing key {e}") from e
    if not isinstance(times, list) or not isinstance(iters, list):
        raise ValueError(f"{path}: times/iters must be arrays")
    if len(times) != len(iters):
        raise ValueError(
            f"{path}: times/iters length mismatch ({len(times)} vs {len(iters)})"
        )
    return times, iters


def weighted_p99_ns(times: list[float], iters: list[float]) -> float:
    """Nearest-rank p99 over the multiset of per-iteration nanoseconds."""
    expanded: list[float] = []
    for t, n in zip(times, iters, strict=True):
        ni = int(n)
        if ni <= 0:
            continue
        per_iter = float(t) / float(n)
        expanded.extend([per_iter] * ni)
    if not expanded:
        raise ValueError("no samples after expansion (empty times/iters?)")
    expanded.sort()
    n = len(expanded)
    rank = int(math.ceil(0.99 * n))
    idx = min(n - 1, rank - 1)
    return expanded[idx]
