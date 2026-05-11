"""Gate: analytics backend selection follows :envvar:`ENVIRONMENT`."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_SRC_ORCH = Path(__file__).resolve().parents[1] / "src"
_SRC_INGESTOR = Path(__file__).resolve().parents[2] / "ingestor" / "src"
for _p in (_SRC_ORCH, _SRC_INGESTOR):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


def test_factory_selects_local_for_development(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENVIRONMENT", "development")
    from orchestrator.analytics.duck_provider import LocalAnalytics
    from orchestrator.analytics.factory import build_analytics_provider

    p = build_analytics_provider()
    try:
        assert isinstance(p, LocalAnalytics)
    finally:
        p.close()


def test_factory_selects_cloud_for_production(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENVIRONMENT", "production")
    from orchestrator.analytics.cloud_provider import CloudAnalytics
    from orchestrator.analytics.factory import build_analytics_provider

    p = build_analytics_provider()
    try:
        assert isinstance(p, CloudAnalytics)
    finally:
        p.close()
