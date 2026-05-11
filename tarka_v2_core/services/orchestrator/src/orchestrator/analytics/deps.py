"""FastAPI dependencies for the analytics plane."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request

from orchestrator.analytics.provider import AnalyticsProvider


def get_analytics(request: Request) -> AnalyticsProvider | None:
    """Return the process-wide :class:`~orchestrator.analytics.provider.AnalyticsProvider` (or ``None``)."""
    return getattr(request.app.state, "analytics", None)


AnalyticsProviderDep = Annotated[AnalyticsProvider | None, Depends(get_analytics)]
