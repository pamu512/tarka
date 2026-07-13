from __future__ import annotations

import time

from minute_rate_limit import MinuteRateLimiter


def test_allows_then_limits_per_key() -> None:
    lim = MinuteRateLimiter(max_events=2, window=60.0)
    assert lim.allow("k") is True
    assert lim.allow("k") is True
    assert lim.allow("k") is False


def test_keys_are_isolated() -> None:
    lim = MinuteRateLimiter(max_events=1, window=60.0)
    assert lim.allow("a") is True
    assert lim.allow("b") is True
    assert lim.allow("a") is False


def test_window_recycles_slots() -> None:
    lim = MinuteRateLimiter(max_events=1, window=0.05)
    assert lim.allow("k") is True
    assert lim.allow("k") is False
    time.sleep(0.06)
    assert lim.allow("k") is True
