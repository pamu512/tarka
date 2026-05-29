"""Gate: durable sink requirement and synchronous handover on ``POST /ingest``."""

from __future__ import annotations

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

from signal_api import ingest_handler  # noqa: E402
from signal_api.ingest_handler import router  # noqa: E402


class _AuditCapture:
    last_execute: tuple[Any, ...] | None = None


class _FakeConn:
    async def execute(self, query: str, *args: Any) -> str:
        _AuditCapture.last_execute = (query, args)
        return "INSERT 0 1"


class _FakePool:
    def acquire(self) -> Any:
        class _Ctx:
            async def __aenter__(self) -> _FakeConn:
                return _FakeConn()

            async def __aexit__(self, *exc: Any) -> None:
                return None

        return _Ctx()


def _body(sid: str) -> dict[str, Any]:
    return {
        "ch": "a" * 64,
        "wv": "ANGLE",
        "dm": 8,
        "ip": "203.0.113.9",
        "px": False,
        "ua": "Mozilla/5.0 (ingest-handler-gate)",
        "sid": sid,
        "ts": datetime.now(UTC).isoformat(),
        "sv": "98.0.0",
        "mv": 0.0,
        "tp": 0,
        "hh": False,
    }


@pytest.fixture
async def ingester_no_sinks() -> AsyncClient:
    app = FastAPI()
    app.state.redis = FakeAsyncRedis(decode_responses=True)
    app.include_router(router, prefix="/v1/signals")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        ac._test_app = app  # noqa: SLF001
        yield ac


@pytest.fixture
async def ingester_with_sinks(monkeypatch: pytest.MonkeyPatch) -> AsyncClient:
    monkeypatch.setenv("SYSTEM_SECRET", "ingest-handler-sync-gate-secret")
    app = FastAPI()
    app.state.redis = FakeAsyncRedis(decode_responses=True)
    app.state.audit_pool = _FakePool()
    app.state.nats_js = AsyncMock()
    app.include_router(router, prefix="/v1/signals")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        ac._test_app = app  # noqa: SLF001
        yield ac


@pytest.mark.anyio
async def test_ingest_fails_503_without_durable_sinks(ingester_no_sinks: AsyncClient) -> None:
    sid = "99999999-9999-9999-9999-999999999999"
    body = _body(sid)

    r = await ingester_no_sinks.post("/v1/signals/ingest", json=body)
    assert r.status_code == 503
    assert r.json()["detail"] == "No durable persistence configured"

    redis = ingester_no_sinks._test_app.state.redis  # noqa: SLF001
    ip_key = "velocity:ip:203.0.113.9:1m"
    dev_key = f"velocity:device:{'a' * 64}:5m"
    assert await redis.get(ip_key) is None
    assert await redis.get(dev_key) is None
    assert await redis.get(f"seen:{sid}") is None


@pytest.mark.anyio
async def test_ingest_success_with_sync_handover(
    ingester_with_sinks: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _AuditCapture.last_execute = None
    handover_completed = False
    real_handover = ingest_handler.durable_intent_handover

    async def _tracking_handover(**kwargs: Any) -> None:
        nonlocal handover_completed
        await real_handover(**kwargs)
        handover_completed = True

    monkeypatch.setattr(ingest_handler, "durable_intent_handover", _tracking_handover)

    sid = "88888888-8888-8888-8888-888888888888"
    r = await ingester_with_sinks.post("/v1/signals/ingest", json=_body(sid))
    assert r.status_code == 201
    assert handover_completed is True
    assert _AuditCapture.last_execute is not None

    js = ingester_with_sinks._test_app.state.nats_js  # noqa: SLF001
    js.publish.assert_awaited_once()
