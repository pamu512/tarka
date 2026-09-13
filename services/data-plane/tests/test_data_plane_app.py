"""Data-plane app smoke tests (post platform-compat removal)."""

from __future__ import annotations

import importlib
import inspect


def test_compat_platform_removed() -> None:
    """A10: the dark data-platform compat surface must not ship anymore."""
    try:
        importlib.import_module("data_plane.platform")
    except ModuleNotFoundError:
        pass
    else:  # pragma: no cover - fails loudly if the module returns
        raise AssertionError("data_plane.platform should have been removed")

    import data_plane.main as dm

    src = inspect.getsource(dm)
    assert "TARKA_PLATFORM_COMPAT_PORT" not in src
    assert "_serve_platform_compat" not in src


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
