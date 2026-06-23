"""POST /v1/compare/manifests integration tests."""

from __future__ import annotations

import uuid
from typing import Any

import pytest
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
    def __init__(self, by_mid: dict[str, tuple[Any, ...]]) -> None:
        self._by_mid = by_mid

    def query(
        self,
        sql: str,
        parameters: dict[str, Any] | None = None,
        settings: dict[str, Any] | None = None,
        **_kw: Any,
    ) -> _QR:
        mid = (parameters or {}).get("mid", "")
        row = self._by_mid.get(str(mid))
        if row is None:
            return _QR([])
        return _QR([row])


def _row(
    trace: list[dict[str, Any]], sig: dict[str, str], final: int
) -> tuple[Any, ...]:
    return (
        trace,
        sig,
        "eng",
        100,
        final,
        50,
    )


@pytest.fixture
async def asgi_client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.mark.asyncio
async def test_compare_manifests_highlights_boolean_fork(
    asgi_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("API_KEYS", "cmp-key")
    monkeypatch.setenv("ALLOW_INSECURE_NO_AUTH", "false")

    ma = uuid.uuid4()
    mb = uuid.uuid4()
    trace_common = [
        {
            "rule_id": "gate",
            "logic_operator": "",
            "operands": [],
            "result": True,
            "state_snapshot": {},
        }
    ]
    ta = trace_common + [
        {
            "rule_id": "shadow_rule",
            "logic_operator": "",
            "operands": [],
            "result": False,
            "state_snapshot": {},
        }
    ]
    tb = trace_common + [
        {
            "rule_id": "shadow_rule",
            "logic_operator": "",
            "operands": [],
            "result": True,
            "state_snapshot": {},
        }
    ]

    prev = getattr(app.state, "clickhouse_client", None)
    app.state.clickhouse_client = _FakeCH(
        {
            str(ma): _row(ta, {"x": "1"}, 0),
            str(mb): _row(tb, {"x": "1"}, 1),
        }
    )
    try:
        r = await asgi_client.post(
            "/v1/compare/manifests",
            headers={"x-api-key": "cmp-key"},
            json={"manifest_id_a": str(ma), "manifest_id_b": str(mb)},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["divergence"]["first_divergence_step_index"] == 1
        assert body["divergence"]["culprit_rule_id"] == "shadow_rule"
        assert body["divergence"]["divergence_category"] == "rule_boolean_result"
        assert body["metadata_diff"]["final_decision"]["match"] is False
        rows = body["intermediate_states_and_execution_path"]
        assert rows[1]["alignment"] == "both"
        assert rows[1]["fields"]["result"]["match"] is False
    finally:
        app.state.clickhouse_client = prev


@pytest.mark.asyncio
async def test_compare_manifests_404_tags_missing_side(
    asgi_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("API_KEYS", "cmp-key")

    ma = uuid.uuid4()
    mb = uuid.uuid4()
    prev = getattr(app.state, "clickhouse_client", None)
    app.state.clickhouse_client = _FakeCH({str(ma): _row([], {}, 0)})
    try:
        r = await asgi_client.post(
            "/v1/compare/manifests",
            headers={"x-api-key": "cmp-key"},
            json={"manifest_id_a": str(ma), "manifest_id_b": str(mb)},
        )
        assert r.status_code == 404
        detail = r.json()["detail"]
        assert detail["missing_manifest_role"] == "manifest_b"
        assert detail["manifest_id"] == str(mb)
    finally:
        app.state.clickhouse_client = prev
