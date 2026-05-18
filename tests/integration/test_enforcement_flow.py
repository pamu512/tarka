"""
Prompt 108: enforcement flow integration — SDK ingest → Redis velocity → policy eval (BLOCK) → Postgres audit.

Production path: browser SDK posts ``POST /ingest`` (Anumana hot path); transactions are evaluated via
``POST /v1/ingest`` → rule-engine ``/v1/evaluate`` (Rust-backed ``tarka_rule_engine`` in deployment).
This test chains the same orchestrator surfaces with an in-memory Redis stand-in and SQLite audit DB.

Gate: wall time for the four instrumented stages (end-to-end within the TestClient session) is < 50ms.
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

import pytest
from sqlalchemy import select
from starlette.testclient import TestClient

_REPO = Path(__file__).resolve().parents[2]
_SRC_ORCH = _REPO / "tarka_v2_core/services/orchestrator/src"
_SRC_INGESTOR = _REPO / "tarka_v2_core/services/ingestor/src"
_SRC_SHARED = _REPO / "tarka_v2_core/services/shared"
for _p in (_SRC_ORCH, _SRC_INGESTOR, _SRC_SHARED):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

# --- Redis pipeline fake (matches ``redis.asyncio`` pipeline used by ``run_ingest_pipeline``) ---


class _FakePipeline:
    def __init__(self, parent: "_FakeRedis") -> None:
        self._parent = parent
        self._ops: list[tuple[str, ...]] = []

    def lpush(self, key: str, value: bytes) -> None:
        self._ops.append(("lpush", key, value))

    def incr(self, key: str) -> None:
        self._ops.append(("incr", key))

    def expire(self, key: str, ttl: int) -> None:
        self._ops.append(("expire", key, ttl))

    def zadd(self, key: str, mapping: dict) -> None:
        self._ops.append(("zadd", key, mapping))

    async def execute(self) -> list[int]:
        out: list[int] = []
        for op in self._ops:
            if op[0] == "lpush":
                await self._parent.lpush(op[1], op[2])
                out.append(1)
            elif op[0] == "incr":
                n = await self._parent.incr(op[1])
                out.append(n)
            elif op[0] == "expire":
                self._parent.expires.append((op[1], int(op[2])))
                out.append(1)
            elif op[0] == "zadd":
                n = await self._parent.zadd(op[1], op[2])
                out.append(n)
        return out


class _FakeRedis:
    def __init__(self) -> None:
        self.pushes: list[tuple[str, bytes]] = []
        self.strings: dict[str, str] = {}
        self.expires: list[tuple[str, int]] = []
        self.zsets: dict[str, dict[str, float]] = {}

    def pipeline(self, transaction: bool = False) -> _FakePipeline:
        _ = transaction
        return _FakePipeline(self)

    async def lpush(self, key: str, value: bytes) -> int:
        self.pushes.append((key, value))
        return 1

    async def incr(self, key: str) -> int:
        cur = int(self.strings.get(key, "0")) + 1
        self.strings[key] = str(cur)
        return cur

    async def zadd(self, key: str, mapping: dict) -> int:
        slot = self.zsets.setdefault(key, {})
        for mk, score in mapping.items():
            mk_s = mk.decode("utf-8") if isinstance(mk, bytes) else str(mk)
            slot[mk_s] = float(score)
        return len(mapping)

    async def aclose(self) -> None:
        return None


# --- httpx stand-in for rule-engine ``/v1/evaluate`` (Rust eval contract in production) ---


class _DummyUpstreamResponse:
    def __init__(self, payload: dict[str, object]) -> None:
        self._payload = payload
        self.status_code = 200
        self.text = json.dumps(payload)

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, object]:
        return self._payload


class _EvalOnlyAsyncClient:
    def __init__(self, evaluate_json: dict[str, object]) -> None:
        self._evaluate_json = evaluate_json

    async def __aenter__(self) -> _EvalOnlyAsyncClient:
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    async def post(
        self,
        url: str,
        json: dict[str, object] | None = None,
        **kwargs: object,
    ) -> _DummyUpstreamResponse:
        if "/v1/evaluate" in url:
            return _DummyUpstreamResponse(self._evaluate_json)
        raise AssertionError(f"unexpected post url: {url!r}")


def _device_velocity_1m_count(fake: _FakeRedis) -> int:
    for k, v in fake.strings.items():
        if ":device:1m:" in k:
            return int(v)
    return 0


def test_enforcement_flow_sdk_redis_eval_postgres_under_50ms(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pytest.importorskip("aiosqlite", reason="in-memory audit DB (same URL as orchestrator tests)")
    pytest.importorskip("multipart", reason="orchestrator routes include multipart File uploads")

    import orchestrator.models.cases  # noqa: F401, PLC0415
    import orchestrator.models.decision  # noqa: F401, PLC0415
    import tarka_shared.audit_trail  # noqa: F401, PLC0415
    import tarka_shared.engine_rules  # noqa: F401, PLC0415
    import tarka_shared.fraud_rules  # noqa: F401, PLC0415

    from orchestrator.main import create_app
    from orchestrator.models.decision import DecisionORM

    rule_id = "00000000-0000-0000-0000-00000000c0de"
    txn = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
    evaluate_json: dict[str, object] = {
        "actions": ["BLOCK"],
        "transaction_id": txn,
        "evaluation_trace": [
            {
                "rule_id": rule_id,
                "rule_name": "demo_stress_block_lane",
                "priority": 5,
                "matched": True,
                "action": "BLOCK",
            },
        ],
        "blocking_rule_id": rule_id,
    }

    monkeypatch.setattr(
        "orchestrator.transaction_ingest.httpx.AsyncClient",
        lambda *a, **k: _EvalOnlyAsyncClient(evaluate_json),
    )

    fake = _FakeRedis()
    app = create_app(
        rule_engine_url="http://rules.test",
        shadow_agent_url=None,
        audit_database_url="sqlite+aiosqlite:///:memory:",
        anumana_redis_client=fake,
    )

    canvas = "cd" * 32
    gate_ms = 50.0
    marks: list[tuple[str, float]] = []
    total_ms: float = 0.0
    stage_ms: list[tuple[str, float]] = []

    async def _assert_decision_row() -> None:
        fac = app.state.audit_session_factory
        assert fac is not None
        async with fac() as session:
            rows = (await session.scalars(select(DecisionORM))).all()
        assert len(rows) == 1
        row = rows[0]
        assert row.entity_id == txn
        assert row.final_decision == "BLOCK"
        assert row.blocking_rule_id == rule_id

    with TestClient(app) as client:
        t0 = time.perf_counter()

        # Stage 1 — SDK-shaped browser telemetry ingest (same JSON surface as TS ``buildBrowserTelemetryIngestJson``).
        r_sdk = client.post(
            "/ingest",
            json={
                "canvas_fingerprint": canvas,
                "canvas_raster_digest_hex": None,
                "ip": "192.0.2.55",
                "tenant_id": "enforcement-gate",
                "device_session_id": "sess-enf-1",
                "telemetry_packet": None,
            },
            headers={"X-Forwarded-For": "198.51.100.2"},
        )
        assert r_sdk.status_code == 200, r_sdk.text
        assert r_sdk.json().get("accepted") is True
        marks.append(("sdk_ingest", time.perf_counter()))

        # Stage 2 — Redis velocity counter materialized (device 1m bucket).
        dv = _device_velocity_1m_count(fake)
        assert dv >= 1, "expected at least one device :1m: velocity INCR"
        marks.append(("redis_counters", time.perf_counter()))

        # Stage 3 — orchestrator → rule-engine evaluate (Rust in prod); mocked here as instant BLOCK.
        r_eval = client.post(
            "/v1/ingest",
            json={
                "entity_id": txn,
                "amount": 50.0,
                "timestamp": "2026-05-09T12:00:00+00:00",
                "metadata": {"lane": "STRESS_BLOCK_LANE"},
            },
        )
        assert r_eval.status_code == 200, r_eval.text
        body = r_eval.json()
        assert body["rule_engine"]["actions"] == ["BLOCK"]
        assert body["rule_engine"]["blocking_rule_id"] == rule_id
        marks.append(("rust_eval_contract", time.perf_counter()))

        asyncio.run(_assert_decision_row())
        marks.append(("postgres_audit", time.perf_counter()))

        total_ms = (marks[-1][1] - t0) * 1000.0
        prev = t0
        stage_ms.clear()
        for name, ts in marks:
            stage_ms.append((name, (ts - prev) * 1000.0))
            prev = ts

    assert total_ms < gate_ms, (
        f"gate: enforcement pipeline took {total_ms:.1f}ms (limit {gate_ms}ms); per_stage_ms={stage_ms}"
    )
