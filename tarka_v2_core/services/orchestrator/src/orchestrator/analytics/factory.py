"""Construct the analytics plane implementation from :envvar:`ENVIRONMENT`."""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from orchestrator.analytics.provider import AnalyticsProvider

logger = logging.getLogger(__name__)

_CLOUD_ENV_HINTS = frozenset(
    {
        "production",
        "prod",
        "staging",
        "stage",
        "cloud",
    },
)


def _normalized_environment() -> str:
    raw = (os.environ.get("ENVIRONMENT") or os.environ.get("TARKA_ENVIRONMENT") or "local").strip().lower()
    return raw or "local"


def build_analytics_provider() -> AnalyticsProvider:
    """
    Select **LocalAnalytics** (DuckDB) vs **CloudAnalytics** (ClickHouse) from ``ENVIRONMENT``.

    * ``production`` / ``staging`` / ``cloud`` / … → :class:`~orchestrator.analytics.cloud_provider.CloudAnalytics`
    * everything else (``local``, ``development``, ``demo``, …) → :class:`~orchestrator.analytics.duck_provider.LocalAnalytics`
    """
    from orchestrator.analytics.cloud_provider import CloudAnalytics
    from orchestrator.analytics.duck_provider import LocalAnalytics

    env = _normalized_environment()
    if env in _CLOUD_ENV_HINTS:
        logger.info("orchestrator_analytics_factory env=%s backend=clickhouse", env)
        return CloudAnalytics.from_environment()
    logger.info("orchestrator_analytics_factory env=%s backend=local_duckdb", env)
    return LocalAnalytics.from_environment()
