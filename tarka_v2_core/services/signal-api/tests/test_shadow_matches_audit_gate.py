"""Gate (Prompt 191): signal ingest persists ``shadow_matches`` on ``audit_logs``."""

from __future__ import annotations

import asyncio
import json
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

from signal_api.ingest_handler import router  # noqa: E402
from signal_api.shadow_counter_sync import SHADOW_RULES_ACTIVE_KEY  # noqa: E402


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


@pytest.fixture
async def ingester_shadow_audit(monkeypatch: pytest.MonkeyPatch) -> AsyncClient:
    monkeypatch.setenv("SYSTEM_SECRET", "gate-secret-shadow-matches")
    app = FastAPI()
    redis = FakeAsyncRedis(decode_responses=True)
    rules = [
        {
            "id": "shadow_high_dm",
            "metadata": {"is_shadow": True},
            "when": [{"op": "gte", "field": "device_memory", "value": 16}],
        },
    ]
    await redis.set(SHADOW_RULES_ACTIVE_KEY, json.dumps(rules))
    app.state.redis = redis
    app.state.audit_pool = _FakePool()
    app.state.nats_js = AsyncMock()
    app.include_router(router, prefix="/v1/signals")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


def _body(sid: str) -> dict[str, Any]:
    return {
        "ch": "d" * 64,
        "wv": "ANGLE",
        "dm": 32,
        "ip": "203.0.113.8",
        "px": False,
        "ua": "Mozilla/5.0",
        "sid": sid,
        "ts": datetime.now(UTC).isoformat(),
        "sv": "91.0.0",
        "mv": 0.0,
        "tp": 0,
        "hh": False,
    }


@pytest.mark.anyio
async def test_audit_insert_includes_shadow_matches(ingester_shadow_audit: AsyncClient) -> None:
    _AuditCapture.last_execute = None
    sid = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    r = await ingester_shadow_audit.post("/v1/signals/ingest", json=_body(sid))
    assert r.status_code == 201
    await asyncio.sleep(0.15)

    assert _AuditCapture.last_execute is not None
    _q, args = _AuditCapture.last_execute
    assert "shadow_matches" in _q
    shadow_matches = args[4]
    assert isinstance(shadow_matches, list)
    assert len(shadow_matches) == 1
    assert shadow_matches[0]["rule_id"] == "shadow_high_dm"
    assert shadow_matches[0]["matched"] is True
    assert "recorded_at" in shadow_matches[0]
