"""Sliding-window circuit breaker for ``tarka_rule_engine`` (Rust / PyO3) FFI calls."""

from __future__ import annotations

import threading
import time
from collections import deque

from decision_api.config import settings

_FAILURE_LOCK = threading.Lock()
_FAILURE_TIMES: deque[float] = deque()


def _window_s() -> float:
    return float(getattr(settings, "rust_ffi_circuit_window_seconds", 60.0))


def _threshold() -> int:
    return max(1, int(getattr(settings, "rust_ffi_circuit_failure_threshold", 5)))


def _prune(now: float) -> None:
    w = _window_s()
    while _FAILURE_TIMES and _FAILURE_TIMES[0] < now - w:
        _FAILURE_TIMES.popleft()


def failures_in_window() -> int:
    """Count of Rust FFI failures in the current sliding window (for metrics / logs)."""
    now = time.monotonic()
    with _FAILURE_LOCK:
        _prune(now)
        return len(_FAILURE_TIMES)


def circuit_is_open() -> bool:
    """True when failure count in window >= threshold — do not call into Rust."""
    return failures_in_window() >= _threshold()


def record_rust_ffi_failure() -> int:
    """Record one failure; return failure count in window after append."""
    now = time.monotonic()
    with _FAILURE_LOCK:
        _prune(now)
        _FAILURE_TIMES.append(now)
        _prune(now)
        return len(_FAILURE_TIMES)


def record_rust_ffi_success() -> None:
    """Clear failure window after a successful Rust evaluation (closes circuit)."""
    with _FAILURE_LOCK:
        _FAILURE_TIMES.clear()
