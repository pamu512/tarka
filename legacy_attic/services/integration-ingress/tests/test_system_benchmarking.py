"""Unit tests for system benchmarking helpers (Prompt 178)."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

from integration_ingress import system_benchmarking as _mod


def test_classify_vs_target() -> None:
    assert _mod.classify_vs_target(0.8) == "on_target"
    assert _mod.classify_vs_target(1.5) == "near_target"
    assert _mod.classify_vs_target(3.0) == "over_target"
    assert _mod.classify_vs_target(None) == "unavailable"


def test_percentile_and_bench_row() -> None:
    row = _mod._bench_row(
        probe_id="t",
        label="Test",
        plane="host",
        samples=[0.5, 0.8, 1.2, 0.9, 1.0, 0.7, 2.5],
    )
    assert row["p95_ms"] is not None
    assert row["status"] in ("on_target", "near_target", "over_target")
    assert _mod._percentile([2.0], 50) == 2.0
    empty = _mod._bench_row(probe_id="e", label="E", plane="host", samples=[])
    assert empty["status"] == "unavailable"


def test_probe_redis_once_paths() -> None:
    row = asyncio.run(_mod._probe_redis_once(None, ""))
    assert row["reachable"] is False

    redis = MagicMock()
    redis.ping = AsyncMock()
    ok = asyncio.run(_mod._probe_redis_once(redis, ""))
    assert ok["reachable"] is True
    assert ok["latency_ms"] is not None

    redis.ping = AsyncMock(side_effect=OSError("redis down"))
    fail = asyncio.run(_mod._probe_redis_once(redis, ""))
    assert fail["reachable"] is False


def test_sample_http_get_hides_exception_detail() -> None:
    http = MagicMock()
    http.get = AsyncMock(side_effect=RuntimeError("secret connection string"))
    samples, err = asyncio.run(_mod._sample_http_get(http, "http://127.0.0.1:1/health", 3))
    assert samples == []
    assert err == "probe failed"
    assert "secret" not in (err or "")


def test_sample_http_get_empty_url() -> None:
    samples, err = asyncio.run(_mod._sample_http_get(MagicMock(), "  ", 3))
    assert samples == []
    assert err == "endpoint not configured"


def test_sample_http_get_http_error() -> None:
    http = MagicMock()
    resp = MagicMock()
    resp.status_code = 503
    http.get = AsyncMock(return_value=resp)
    samples, err = asyncio.run(_mod._sample_http_get(http, "http://127.0.0.1/health", 3))
    assert samples == []
    assert err == "HTTP 503"


def test_sample_http_get_success() -> None:
    http = MagicMock()
    resp = MagicMock()
    resp.status_code = 200
    http.get = AsyncMock(return_value=resp)
    samples, err = asyncio.run(_mod._sample_http_get(http, "http://127.0.0.1/health", 3))
    assert len(samples) == 3
    assert err is None


def test_in_process_and_redis_kv_samples() -> None:
    floor = _mod._sample_in_process_floor(4)
    assert len(floor) == 4

    redis = MagicMock()
    redis.set = AsyncMock()
    redis.get = AsyncMock(return_value="x")
    kv = asyncio.run(_mod._sample_redis_kv(redis, "", 3))
    assert len(kv) == 3


def test_build_system_benchmarking_payload() -> None:
    http = MagicMock()
    ok = MagicMock()
    ok.status_code = 200
    http.get = AsyncMock(return_value=ok)

    redis = MagicMock()
    redis.ping = AsyncMock()
    redis.set = AsyncMock()
    redis.get = AsyncMock(return_value="x")

    payload = asyncio.run(
        _mod.build_system_benchmarking_payload(
            http=http,
            redis_client=redis,
            redis_url="redis://127.0.0.1:6379/0",
            sample_rounds=5,
        ),
    )
    assert payload["source"] == "live"
    assert len(payload["probes"]) >= 5
    assert "summary" in payload
