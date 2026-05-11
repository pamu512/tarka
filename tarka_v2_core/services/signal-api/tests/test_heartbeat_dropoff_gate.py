"""
Gate: tab-close simulation → ``session:{uuid}:dropoff`` is set; a second client (Orchestrator) can ``GET`` it.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest
from fakeredis import FakeAsyncRedis
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

_SRC = Path(__file__).resolve().parents[1] / "src"
_REPO = Path(__file__).resolve().parents[4]
for _p in (_SRC, _REPO):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from signal_api.heartbeat import (  # noqa: E402
    dropoff_flag_key,
    scan_stale_sessions_for_dropoff,
)
from signal_api.heartbeat import router as heartbeat_router  # noqa: E402


@pytest.fixture
async def hb_client() -> AsyncClient:
    app = FastAPI()
    app.state.redis = FakeAsyncRedis(decode_responses=True)
    app.include_router(heartbeat_router, prefix="/v1/heartbeat")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        ac._test_app = app  # noqa: SLF001
        yield ac


@pytest.mark.anyio
async def test_tab_close_dropoff_flag_readable_by_orchestrator(hb_client: AsyncClient) -> None:
    """Orchestrator shares Redis: read ``session:{sid}:dropoff`` after stale ping + monitor scan."""
    sid = "cccccccc-cccc-cccc-cccc-cccccccccccc"
    r = await hb_client.post("/v1/heartbeat/ping", json={"session_id": sid})
    assert r.status_code == 204

    redis = hb_client._test_app.state.redis  # noqa: SLF001
    zkey = "signal:heartbeat:watch"
    await redis.zadd(zkey, {sid: 1.0})

    with patch("signal_api.heartbeat.time") as mt:
        mt.time.return_value = 500.0
        stats = await scan_stale_sessions_for_dropoff(redis)

    assert stats["flagged"] >= 1
    dkey = dropoff_flag_key(sid)
    orch_val = await redis.get(dkey)
    assert orch_val is not None
    assert orch_val in (b"1", "1")
    ttl = await redis.ttl(dkey)
    assert ttl > 0
    assert ttl <= 300


@pytest.mark.anyio
async def test_logout_prevents_dropoff(hb_client: AsyncClient) -> None:
    sid = "dddddddd-dddd-dddd-dddd-dddddddddddd"
    await hb_client.post("/v1/heartbeat/ping", json={"session_id": sid})
    await hb_client.post("/v1/heartbeat/logout", json={"session_id": sid})
    redis = hb_client._test_app.state.redis  # noqa: SLF001
    await redis.zadd("signal:heartbeat:watch", {sid: 1.0})
    with patch("signal_api.heartbeat.time") as mt:
        mt.time.return_value = 900.0
        stats = await scan_stale_sessions_for_dropoff(redis)
    assert stats["flagged"] == 0
    assert await redis.get(dropoff_flag_key(sid)) is None
