"""Simple sliding-window rate limiter (per key, in-process)."""

from __future__ import annotations

import time
from collections import defaultdict, deque
from threading import Lock


class MinuteRateLimiter:
    """At most `max_events` calls per `window` seconds per distinct key."""

    __slots__ = ("max_events", "window", "_dq", "_lock")

    def __init__(self, max_events: int, window: float = 60.0) -> None:
        self.max_events = max(1, int(max_events))
        self.window = float(window)
        self._dq: dict[str, deque[float]] = defaultdict(deque)
        self._lock = Lock()

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        cutoff = now - self.window
        with self._lock:
            d = self._dq[key]
            while d and d[0] < cutoff:
                d.popleft()
            if len(d) >= self.max_events:
                return False
            d.append(now)
            return True
