"""Smoke: platform app factory and data-plane import remain wired."""

from __future__ import annotations


def test_platform_app_factory_title() -> None:
    from data_plane.platform.app import create_platform_app

    app = create_platform_app(with_observability=False)
    assert "Data Platform" in app.title
    paths = {getattr(r, "path", None) for r in app.routes}
    assert "/v1/health" in paths
    assert "/v1/events" in paths
    assert "/v1/analytics/decisions" in paths


def test_data_plane_app_imports() -> None:
    from data_plane.main import app

    assert "Data Plane" in app.title


def test_data_plane_exposes_one_ready_and_one_health() -> None:
    """Merged ingest/sink must not leave a NATS-only /v1/ready in front."""
    from data_plane.main import app

    ready = [
        r
        for r in app.routes
        if getattr(r, "path", None) == "/v1/ready"
        and "GET" in (getattr(r, "methods", set()) or set())
    ]
    health = [
        r
        for r in app.routes
        if getattr(r, "path", None) == "/v1/health"
        and "GET" in (getattr(r, "methods", set()) or set())
    ]
    assert len(ready) == 1
    assert len(health) == 1
