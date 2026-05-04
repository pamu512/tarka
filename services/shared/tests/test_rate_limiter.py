from __future__ import annotations

import time

from rate_limiter import SKIP_PATHS, TokenBucket


def test_token_bucket_allows_then_limits() -> None:
    bucket = TokenBucket(rate=1.0, burst=2)
    ok1, _ = bucket.allow("k")
    ok2, _ = bucket.allow("k")
    ok3, headers = bucket.allow("k")
    assert ok1 is True
    assert ok2 is True
    assert ok3 is False
    assert "Retry-After" in headers


def test_token_bucket_recovers_with_time() -> None:
    bucket = TokenBucket(rate=100.0, burst=1)
    ok1, _ = bucket.allow("k2")
    assert ok1 is True
    ok2, _ = bucket.allow("k2")
    assert ok2 is False
    time.sleep(0.02)
    ok3, _ = bucket.allow("k2")
    assert ok3 is True


def test_token_bucket_cost_penalizes_suspicious_traffic() -> None:
    bucket = TokenBucket(rate=100.0, burst=5)
    ok1, _ = bucket.allow("k3", cost=3)
    ok2, _ = bucket.allow("k3", cost=3)
    assert ok1 is True
    assert ok2 is False


def test_cleanup_removes_stale_buckets() -> None:
    bucket = TokenBucket(rate=1.0, burst=1)
    bucket.allow("old")
    bucket._buckets["old"] = (0.0, time.monotonic() - 500.0)  # type: ignore[attr-defined]
    bucket.cleanup(max_age=10.0)
    assert "old" not in bucket._buckets  # type: ignore[attr-defined]


def test_health_and_metrics_paths_are_skipped() -> None:
    assert "/v1/health" in SKIP_PATHS
    assert "/metrics" in SKIP_PATHS

