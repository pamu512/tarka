"""Sanity checks for SR-03 / SR-01 fail-closed behavior when ClickHouse is offline."""

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from decision_api.config import settings
from decision_api.deps import get_clickhouse
from decision_api.main import app


def _minimal_request() -> Request:
    return Request(
        {
            "type": "http",
            "path": "/",
            "headers": [],
            "scheme": "http",
            "client": ("test", 0),
            "server": ("test", 80),
            "app": app,
        }
    )


def test_get_clickhouse_503_when_host_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "clickhouse_host", "")
    with pytest.raises(HTTPException) as excinfo:
        get_clickhouse(_minimal_request())
    assert excinfo.value.status_code == 503
    assert excinfo.value.detail["reason_code"] == "ANALYTICS_ENGINE_OFFLINE"


def test_get_clickhouse_503_when_client_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    prev = getattr(app.state, "clickhouse_client", None)
    prev_eng = getattr(app.state, "analytics_engine", None)
    monkeypatch.setattr(settings, "clickhouse_host", "clickhouse")
    app.state.clickhouse_client = None
    app.state.analytics_engine = None
    try:
        with pytest.raises(HTTPException) as excinfo:
            get_clickhouse(_minimal_request())
        assert excinfo.value.status_code == 503
        assert excinfo.value.detail["reason_code"] == "ANALYTICS_ENGINE_OFFLINE"
    finally:
        app.state.clickhouse_client = prev
        app.state.analytics_engine = prev_eng
