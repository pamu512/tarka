"""Gate: 10 identical unified-signal payloads → first **201**, next nine **204** (Redis ``seen:{sid}``)."""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

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


@pytest.fixture
async def ingester() -> AsyncClient:
    """Single asyncio loop — required for ``FakeAsyncRedis`` + ASGI."""
    app = FastAPI()
    app.state.redis = FakeAsyncRedis(decode_responses=True)
    app.include_router(router, prefix="/v1/signals")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        ac._test_app = app  # noqa: SLF001 — test-only handle to read fake Redis
        yield ac


def _valid_body(sid: str) -> dict:
    return {
        "ch": "b" * 64,
        "wv": "Google Inc. (ANGLE)",
        "dm": 8,
        "ip": "198.51.100.42",
        "px": False,
        "ua": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36",
        "sid": sid,
        "ts": datetime.now(UTC).isoformat(),
        "sv": "0.9.0-test",
        "mv": 0.0,
        "tp": 0,
        "hh": False,
    }


@pytest.mark.anyio
async def test_ten_identical_payloads_first_201_then_nine_204(ingester: AsyncClient) -> None:
    sid = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    UUID(sid)  # must be valid UUID for schema
    body = _valid_body(sid)

    codes: list[int] = []
    for _ in range(10):
        r = await ingester.post("/v1/signals/ingest", json=body)
        codes.append(r.status_code)

    assert codes[0] == 201
    assert codes[1:] == [204] * 9


@pytest.mark.anyio
async def test_velocity_keys_incremented_once(ingester: AsyncClient) -> None:
    sid = "11111111-2222-3333-4444-555555555555"
    body = _valid_body(sid)
    r = await ingester.post("/v1/signals/ingest", json=body)
    assert r.status_code == 201

    redis = ingester._test_app.state.redis  # noqa: SLF001
    ip_key = "velocity:ip:198.51.100.42:1m"
    dev_key = f"velocity:device:{'b' * 64}:5m"

    ip_v, dev_v = await redis.get(ip_key), await redis.get(dev_key)
    assert ip_v == "1"
    assert dev_v == "1"

    await ingester.post("/v1/signals/ingest", json=body)
    ip_v2, dev_v2 = await redis.get(ip_key), await redis.get(dev_key)
    assert ip_v2 == "1"
    assert dev_v2 == "1"


def test_hiredis_available_when_extra_installed() -> None:
    """Document gate: production installs ``redis[hiredis]`` for native parsing."""
    try:
        import hiredis  # noqa: F401
    except ImportError:
        pytest.skip("hiredis not installed in this environment (optional C accelerator)")
    from redis._parsers import hiredis as hp

    assert hp is not None
