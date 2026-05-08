"""GET /v1/manifest/{id}/visualize — trace_json → Mermaid-oriented JSON."""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from clickhouse_connect.driver.exceptions import DatabaseError
from httpx import ASGITransport, AsyncClient

from decision_api.main import app


class _QR:
    __slots__ = ("column_names", "result_rows")

    def __init__(self, rows: list[tuple[Any, ...]]) -> None:
        self.column_names = (
            "trace_json",
            "signals",
            "engine_version",
            "timestamp_ns",
            "final_decision",
            "total_execution_time_us",
        )
        self.result_rows = rows


class _FakeCH:
    def __init__(self, rows: list[tuple[Any, ...]]) -> None:
        self._rows = rows

    def query(
        self,
        sql: str,
        parameters: dict[str, Any] | None = None,
        settings: dict[str, Any] | None = None,
        **_kw: Any,
    ) -> _QR:
        _ = sql, parameters, settings
        return _QR(self._rows)


@pytest.fixture
async def asgi_client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.mark.asyncio
async def test_manifest_visualize_ok(
    asgi_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("API_KEYS", "mv-key")
    monkeypatch.setenv("ALLOW_INSECURE_NO_AUTH", "false")

    mid = uuid.UUID("018f1234-5678-7abc-8def-123456789abc")
    trace = [
        {
            "rule_id": "rule_a",
            "logic_operator": "",
            "operands": [],
            "result": True,
            "state_snapshot": {"hits": "2", "nested": '{"x":1}'},
        },
        {
            "rule_id": "rule_b",
            "logic_operator": "AND",
            "operands": ["rule_a"],
            "result": False,
            "state_snapshot": {},
        },
    ]
    prev = getattr(app.state, "clickhouse_client", None)
    app.state.clickhouse_client = _FakeCH(
        [
            (
                trace,
                {"amt": "100"},
                "engine-1",
                99,
                1,
                42,
            )
        ]
    )
    try:
        r = await asgi_client.get(
            f"/v1/manifest/{mid}/visualize",
            headers={"x-api-key": "mv-key"},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["manifest_id"] == str(mid)
        assert "flowchart TD" in body["mermaid_js"]["diagram"]
        assert len(body["mermaid_js"]["nodes"]) == 2
        assert body["execution_path"][0]["state_snapshot_decoded"]["hits"] == 2
        assert body["execution_path"][0]["state_snapshot_decoded"]["nested"] == {"x": 1}
        edge_kinds = {e["kind"] for e in body["mermaid_js"]["edges"]}
        assert "execution" in edge_kinds
        assert "operand_flow" in edge_kinds
        assert body["metadata"]["signals"]["amt"] == "100"
    finally:
        app.state.clickhouse_client = prev


@pytest.mark.asyncio
async def test_manifest_visualize_404(
    asgi_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("API_KEYS", "mv-key")

    prev = getattr(app.state, "clickhouse_client", None)
    app.state.clickhouse_client = _FakeCH([])
    try:
        mid = uuid.uuid4()
        r = await asgi_client.get(
            f"/v1/manifest/{mid}/visualize",
            headers={"x-api-key": "mv-key"},
        )
        assert r.status_code == 404
        assert r.json()["detail"]["reason_code"] == "MANIFEST_NOT_FOUND"
    finally:
        app.state.clickhouse_client = prev


@pytest.mark.asyncio
async def test_manifest_visualize_503_on_clickhouse_error(
    asgi_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("API_KEYS", "mv-key")

    class _BoomCH:
        def query(
            self,
            sql: str,
            parameters: dict[str, Any] | None = None,
            settings: dict[str, Any] | None = None,
            **_kw: Any,
        ) -> _QR:
            raise DatabaseError("simulated")

    prev = getattr(app.state, "clickhouse_client", None)
    app.state.clickhouse_client = _BoomCH()
    try:
        r = await asgi_client.get(
            f"/v1/manifest/{uuid.uuid4()}/visualize",
            headers={"x-api-key": "mv-key"},
        )
        assert r.status_code == 503
        assert r.json()["detail"]["reason_code"] == "MANIFEST_CLICKHOUSE_ERROR"
    finally:
        app.state.clickhouse_client = prev
