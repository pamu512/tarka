"""Gate: audit Postgres circuit (5 timeouts → degraded, skip PG); ingest stays on Redis fast-path."""

from __future__ import annotations

import asyncio
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import pytest
from fakeredis import FakeAsyncRedis
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

_SRC = Path(__file__).resolve().parents[1] / "src"
_REPO_ROOT = Path(__file__).resolve().parents[3]
for _p in (_SRC, _REPO_ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from signal_api.durable_handover import durable_intent_handover  # noqa: E402
from signal_api.ingest_handler import router  # noqa: E402
from signal_api.middleware.audit_circuit import (  # noqa: E402
    AuditDegradedModeHeaderMiddleware,
    AuditPostgresCircuitBreaker,
)
from tarka_v2_core.schemas.ingestion import UnifiedSignalSchema  # noqa: E402


def _body(sid: str) -> dict[str, Any]:
    return {
        "ch": "c" * 64,
        "wv": "ANGLE",
        "dm": 8,
        "ip": "203.0.113.7",
        "px": False,
        "ua": "Mozilla/5.0 (compatible; circuit-gate)",
        "sid": sid,
        "ts": datetime.now(UTC).isoformat(),
        "sv": "97.0.0",
        "mv": 0.0,
        "tp": 0,
        "hh": False,
    }


@pytest.mark.anyio
async def test_five_audit_timeouts_then_skips_postgres_acquire() -> None:
    """Five bounded waits time out → circuit opens; next handover does not call ``pool.acquire``."""

    class _SlowConn:
        async def execute(self, *_a: Any, **_k: Any) -> str:
            await asyncio.sleep(3600)
            return "INSERT 0 1"

    class _Pool:
        acquire_calls = 0

        def acquire(self) -> Any:
            class _Ctx:
                async def __aenter__(self) -> _SlowConn:
                    _Pool.acquire_calls += 1
                    return _SlowConn()

                async def __aexit__(self, *_exc: Any) -> None:
                    return None

            return _Ctx()

    circuit = AuditPostgresCircuitBreaker(
        execute_timeout_sec=0.05,
        open_after_timeouts=5,
        degraded_duration_sec=60.0,
    )
    body = UnifiedSignalSchema.model_validate(_body("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"))
    canon = b"{}"

    for _ in range(5):
        await durable_intent_handover(
            pool=_Pool(),
            js=None,
            body=body,
            canonical_bytes=canon,
            integrity_hex="0" * 64,
            circuit=circuit,
        )

    assert _Pool.acquire_calls == 5
    assert circuit.is_degraded()

    await durable_intent_handover(
        pool=_Pool(),
        js=None,
        body=body,
        canonical_bytes=canon,
        integrity_hex="0" * 64,
        circuit=circuit,
    )
    assert _Pool.acquire_calls == 5, "degraded mode must skip Postgres acquire"


@pytest.mark.anyio
async def test_success_resets_consecutive_timeouts() -> None:
    class _OkConn:
        async def execute(self, *_a: Any, **_k: Any) -> str:
            return "INSERT 0 1"

    class _Pool:
        def acquire(self) -> Any:
            class _Ctx:
                async def __aenter__(self) -> _OkConn:
                    return _OkConn()

                async def __aexit__(self, *_exc: Any) -> None:
                    return None

            return _Ctx()

    circuit = AuditPostgresCircuitBreaker(
        execute_timeout_sec=0.05,
        open_after_timeouts=3,
        degraded_duration_sec=60.0,
    )
    body = UnifiedSignalSchema.model_validate(_body("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"))
    canon = b"{}"

    class _SlowConn:
        async def execute(self, *_a: Any, **_k: Any) -> str:
            await asyncio.sleep(3600)
            return "x"

    class _SlowPool:
        def acquire(self) -> Any:
            class _Ctx:
                async def __aenter__(self) -> _SlowConn:
                    return _SlowConn()

                async def __aexit__(self, *_exc: Any) -> None:
                    return None

            return _Ctx()

    await durable_intent_handover(
        pool=_SlowPool(), js=None, body=body, canonical_bytes=canon, integrity_hex="a" * 64, circuit=circuit
    )
    await durable_intent_handover(
        pool=_SlowPool(), js=None, body=body, canonical_bytes=canon, integrity_hex="a" * 64, circuit=circuit
    )
    await durable_intent_handover(
        pool=_Pool(), js=None, body=body, canonical_bytes=canon, integrity_hex="a" * 64, circuit=circuit
    )
    assert not circuit.is_degraded()


@pytest.mark.anyio
async def test_ingest_returns_201_when_audit_postgres_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    """Redis fast-path: HTTP **201** even when background audit cannot use Postgres (simulated disconnect)."""

    class _DeadPool:
        def acquire(self) -> Any:
            class _Ctx:
                async def __aenter__(self) -> Any:
                    raise ConnectionRefusedError("simulated postgres down")

                async def __aexit__(self, *_exc: Any) -> None:
                    return None

            return _Ctx()

    monkeypatch.setenv("SYSTEM_SECRET", "circuit-gate-secret-do-not-reuse")

    app = FastAPI()
    app.state.redis = FakeAsyncRedis(decode_responses=True)
    app.state.audit_pool = _DeadPool()
    app.state.audit_circuit = AuditPostgresCircuitBreaker(execute_timeout_sec=1.0, open_after_timeouts=5)
    app.state.nats_js = None
    app.include_router(router, prefix="/v1/signals")
    transport = ASGITransport(app=app)

    sid = "cccccccc-cccc-cccc-cccc-cccccccccccc"
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.post("/v1/signals/ingest", json=_body(sid))
        assert r.status_code == 201


@pytest.mark.anyio
async def test_docker_pause_postgres_ingest_still_201(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Gate (manual / CI): pause the Postgres container, POST ingest, expect **201**.

    Requires ``docker`` on PATH, ``SIGNAL_AUDIT_CIRCUIT_DOCKER_GATE=1``,
    ``SIGNAL_INGEST_GATE_BASE_URL`` (e.g. ``http://127.0.0.1:8788``),
    ``SIGNAL_AUDIT_PG_DOCKER_CONTAINER`` (container name or id from ``docker ps``).
    """
    if not os.environ.get("SIGNAL_AUDIT_CIRCUIT_DOCKER_GATE", "").strip():
        pytest.skip("Set SIGNAL_AUDIT_CIRCUIT_DOCKER_GATE=1 for docker-compose Postgres gate")

    import shutil
    import subprocess

    if shutil.which("docker") is None:
        pytest.skip("docker CLI not found")

    base = (os.environ.get("SIGNAL_INGEST_GATE_BASE_URL") or "").rstrip("/")
    container = (os.environ.get("SIGNAL_AUDIT_PG_DOCKER_CONTAINER") or "").strip()
    if not base or not container:
        pytest.skip("SIGNAL_INGEST_GATE_BASE_URL and SIGNAL_AUDIT_PG_DOCKER_CONTAINER required")

    subprocess.run(["docker", "pause", container], check=True, capture_output=True)
    try:
        async with AsyncClient(base_url=base, timeout=30.0) as ac:
            sid = "dddddddd-dddd-dddd-dddd-dddddddddddd"
            r = await ac.post("/v1/signals/ingest", json=_body(sid))
            assert r.status_code == 201, r.text
    finally:
        subprocess.run(["docker", "unpause", container], check=False, capture_output=True)


@pytest.mark.anyio
async def test_degraded_header_after_circuit_opens(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SYSTEM_SECRET", "hdr-secret-do-not-reuse")

    class _SlowConn:
        async def execute(self, *_a: Any, **_k: Any) -> str:
            await asyncio.sleep(3600)
            return "x"

    class _Pool:
        def acquire(self) -> Any:
            class _Ctx:
                async def __aenter__(self) -> _SlowConn:
                    return _SlowConn()

                async def __aexit__(self, *_exc: Any) -> None:
                    return None

            return _Ctx()

    app = FastAPI()
    app.add_middleware(AuditDegradedModeHeaderMiddleware)
    app.state.redis = FakeAsyncRedis(decode_responses=True)
    app.state.audit_pool = _Pool()
    app.state.audit_circuit = AuditPostgresCircuitBreaker(
        execute_timeout_sec=0.05,
        open_after_timeouts=2,
        degraded_duration_sec=300.0,
    )
    app.state.nats_js = AsyncMock()
    app.include_router(router, prefix="/v1/signals")
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        for i in range(2):
            sid = f"eeeeeeee-eeee-eeee-eeee-{i:012x}"
            body = _body(sid)
            r = await ac.post("/v1/signals/ingest", json=body)
            assert r.status_code == 201
            await asyncio.sleep(0.2)

        sid2 = "ffffffff-ffff-ffff-ffff-ffffffffffff"
        r2 = await ac.post("/v1/signals/ingest", json=_body(sid2))
        assert r2.status_code == 201
        assert r2.headers.get("x-signal-audit-degraded") == "1"
