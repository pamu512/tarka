"""data-plane /v1/ready must not HTTP-200 when the bus is down."""

from __future__ import annotations

from data_plane.main import ready_http


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
