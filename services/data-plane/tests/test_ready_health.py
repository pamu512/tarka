"""data-plane /v1/ready must not HTTP-200 when the bus is down."""

from __future__ import annotations

from fastapi import FastAPI

from data_plane.main import SUBAPP_SKIP_PATHS, _merge_routes, ready_http


def test_subapp_ready_is_not_merged():
    """event-ingest /v1/ready is NATS-only; combined ready must win."""
    src = FastAPI()

    @src.get("/v1/ready")
    def _ready() -> dict[str, bool]:
        return {"ready": True}

    tgt = FastAPI()
    _merge_routes(tgt, src, skip_paths=SUBAPP_SKIP_PATHS)
    assert not any(getattr(route, "path", None) == "/v1/ready" for route in tgt.routes)


def test_ready_http_503_when_nats_down() -> None:
    code, body = ready_http(nats_ok=False, http_ok=True, redis_ok=True)
    assert code == 503
    assert body["ready"] is False


def test_ready_http_200_when_bus_up() -> None:
    code, body = ready_http(nats_ok=True, http_ok=True, redis_ok=True)
    assert code == 200
    assert body["ready"] is True


def test_ready_http_503_when_clickhouse_configured_down() -> None:
    code, body = ready_http(nats_ok=True, http_ok=True, redis_ok=True, clickhouse_ok=False)
    assert code == 503
    assert body["ready"] is False
    assert body["checks"]["clickhouse_ok"] is False


def test_ready_http_200_when_clickhouse_unconfigured() -> None:
    code, body = ready_http(nats_ok=True, http_ok=True, redis_ok=True, clickhouse_ok=None)
    assert code == 200
    assert "clickhouse_ok" not in body["checks"]
