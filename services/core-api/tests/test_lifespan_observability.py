"""Lifespan failure observability.

A dead dependency (redis DNS failure, db down) used to kill core-api with
uvicorn exit 3 and NO traceback in `docker logs` — the exception surfaced
only on stderr of an already-stopped server. These tests pin the contract:
the lifespan wrapper logs the cause loudly before propagating.
"""

from __future__ import annotations

import logging
from logging import Handler

import pytest


class _CaptureHandler(Handler):
    """Capture records bypassing structlog's root-logger rerouting."""

    def __init__(self):
        super().__init__(level=logging.ERROR)
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


def _make_app_with_failing_sub_lifespan(monkeypatch, failure: Exception):
    """Build core_api.main with a decision-api lifespan that raises."""
    import core_api.main as core_main
    from core_api.infrastructure import otel as _otel

    # core_api.main runs create_app() at import (module-level `app`), which
    # consumes the once-per-process otel guard. Reset AFTER import so this
    # test's own create_app() call is allowed.
    _otel._INIT_ATTEMPTED = False
    _otel._INITIALIZED = False

    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def failing_lifespan(app):
        raise failure
        yield  # pragma: no cover

    monkeypatch.setattr(core_main.dec, "lifespan", failing_lifespan)
    return core_main


@pytest.fixture(autouse=True)
def _reset_otel_guard():
    """create_app() wires otel once per process; tests create many apps.

    Reset is also done inside _make_app_with_failing_sub_lifespan AFTER the
    core_api import; this fixture restores the pre-test values on exit.
    """
    from core_api.infrastructure import otel as _otel

    saved_attempted = _otel._INIT_ATTEMPTED
    saved_initialized = getattr(_otel, "_INITIALIZED", False)
    yield
    _otel._INIT_ATTEMPTED = saved_attempted
    _otel._INITIALIZED = saved_initialized


@pytest.mark.asyncio
async def test_lifespan_failure_is_logged_with_traceback(monkeypatch):
    make = _make_app_with_failing_sub_lifespan(
        monkeypatch, RuntimeError("simulated redis DNS failure")
    )
    app = make.create_app()
    handler = _CaptureHandler()
    logger = logging.getLogger("core-api.lifespan")
    logger.addHandler(handler)
    try:
        with pytest.raises(RuntimeError, match="simulated redis DNS failure"):
            async with app.router.lifespan_context(app):
                pass
    finally:
        logger.removeHandler(handler)
    # The wrapper must have logged at ERROR+ with the exception attached.
    with_exc = [r for r in handler.records if r.exc_info]
    assert with_exc, "lifespan failure produced no ERROR record with traceback"
    assert "startup failed" in with_exc[0].getMessage()
    exc_text = with_exc[0].exc_text or ""
    if not exc_text and with_exc[0].exc_info:
        import traceback as _tb

        exc_text = "".join(_tb.format_exception(*with_exc[0].exc_info))
    assert "simulated redis DNS failure" in exc_text


@pytest.mark.asyncio
async def test_lifespan_failure_still_propagates_exit(monkeypatch):
    """Logging must not swallow the failure — uvicorn still exits non-zero."""
    make = _make_app_with_failing_sub_lifespan(
        monkeypatch, ConnectionError("Error -2 connecting to redis:6379")
    )
    app = make.create_app()
    with pytest.raises(ConnectionError, match="redis:6379"):
        async with app.router.lifespan_context(app):
            pass


@pytest.mark.asyncio
async def test_lifespan_success_path_unaffected(caplog):
    """Healthy startup stays quiet — no ERROR records on the happy path."""
    import core_api.main as core_main

    app = core_main.create_app()
    with caplog.at_level(logging.WARNING, logger="core-api.lifespan"):
        async with app.router.lifespan_context(app):
            pass
    errors = [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert not errors
