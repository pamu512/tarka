"""Sink must refuse to start when the analytics backend is not writable.

Fail-closed: ``CloudAnalytics`` with no ClickHouse client silently drops every
row (``append_transaction`` no-ops at debug level). If the duck sink started in
that state it would RPOP live telemetry off Redis and discard it — data loss
masquerading as a healthy worker. The worker must fail fast instead.

``DuckAnalyticsProvider`` (local) is always writable (in-memory DuckDB).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_SRC_ORCH = Path(__file__).resolve().parents[1]
if str(_SRC_ORCH) not in sys.path:
    sys.path.insert(0, str(_SRC_ORCH))

from orchestrator_analytics.cloud_provider import CloudAnalytics  # noqa: E402
from orchestrator_analytics.duck_provider import DuckAnalyticsProvider  # noqa: E402


def test_cloud_analytics_without_client_is_not_writable() -> None:
    p = CloudAnalytics(client=None)
    assert p.writable() is False


def test_duck_analytics_provider_is_writable() -> None:
    p = DuckAnalyticsProvider()
    try:
        assert p.writable() is True
    finally:
        p.close()


def test_worker_env_guard_requires_writable_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    """``build_sink_analytics`` must raise when the provider cannot write."""
    from orchestrator_analytics.factory import build_analytics_provider

    class _NoWrite:
        def writable(self) -> bool:
            return False

    monkeypatch.setattr(
        "workers.anumana_nats_duck_sink.build_analytics_provider",
        lambda: _NoWrite(),
    )
    from workers.anumana_nats_duck_sink import build_sink_analytics

    with pytest.raises(RuntimeError, match="(?i)analytics backend is not writable"):
        build_sink_analytics()
