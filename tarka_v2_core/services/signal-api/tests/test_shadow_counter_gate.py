"""Gate: active shadow rule matches increment ``stats:shadow:{rule_id}:matches`` on first ingest only."""

from __future__ import annotations

import json
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
from signal_api.shadow_counter_sync import (  # noqa: E402
    SHADOW_RULES_ACTIVE_KEY,
    shadow_match_stats_key,
)


@pytest.fixture
async def ingester() -> AsyncClient:
    app = FastAPI()
    app.state.redis = FakeAsyncRedis(decode_responses=True)
    app.include_router(router, prefix="/v1/signals")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        ac._test_app = app  # noqa: SLF001
        yield ac


def _valid_body(sid: str, *, dm: int = 8) -> dict:
    return {
        "ch": "c" * 64,
        "wv": "Google Inc.",
        "dm": dm,
        "ip": "198.51.100.42",
        "px": False,
        "ua": "Mozilla/5.0",
        "sid": sid,
        "ts": datetime.now(UTC).isoformat(),
        "sv": "0.9.0-test",
        "mv": 0.0,
        "tp": 0,
        "hh": False,
    }


@pytest.mark.anyio
async def test_shadow_counter_increments_on_match(ingester: AsyncClient) -> None:
    redis = ingester._test_app.state.redis  # noqa: SLF001
    rules = [
        {
            "id": "shadow_high_memory",
            "metadata": {"is_shadow": True},
            "status": "active",
            "when": [{"op": "gte", "field": "device_memory", "value": 16}],
        },
    ]
    await redis.set(SHADOW_RULES_ACTIVE_KEY, json.dumps(rules))

    sid = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    UUID(sid)
    r = await ingester.post("/v1/signals/ingest", json=_valid_body(sid, dm=32))
    assert r.status_code == 201

    count = await redis.get(shadow_match_stats_key("shadow_high_memory"))
    assert count == "1"


@pytest.mark.anyio
async def test_shadow_counter_no_increment_when_predicate_misses(ingester: AsyncClient) -> None:
    redis = ingester._test_app.state.redis  # noqa: SLF001
    rules = [
        {
            "id": "shadow_high_memory",
            "metadata": {"is_shadow": True},
            "when": [{"op": "gte", "field": "device_memory", "value": 64}],
        },
    ]
    await redis.set(SHADOW_RULES_ACTIVE_KEY, json.dumps(rules))

    sid = "bbbbbbbb-bbbb-cccc-dddd-eeeeeeeeeeee"
    r = await ingester.post("/v1/signals/ingest", json=_valid_body(sid, dm=8))
    assert r.status_code == 201

    count = await redis.get(shadow_match_stats_key("shadow_high_memory"))
    assert count is None


@pytest.mark.anyio
async def test_shadow_counter_skipped_on_dedup_replay(ingester: AsyncClient) -> None:
    redis = ingester._test_app.state.redis  # noqa: SLF001
    rules = [
        {
            "id": "shadow_probe",
            "metadata": {"is_shadow": True},
            "when": [{"op": "gte", "field": "device_memory", "value": 1}],
        },
    ]
    await redis.set(SHADOW_RULES_ACTIVE_KEY, json.dumps(rules))

    sid = "cccccccc-bbbb-cccc-dddd-eeeeeeeeeeee"
    body = _valid_body(sid)
    assert (await ingester.post("/v1/signals/ingest", json=body)).status_code == 201
    assert (await ingester.post("/v1/signals/ingest", json=body)).status_code == 204

    count = await redis.get(shadow_match_stats_key("shadow_probe"))
    assert count == "1"


@pytest.mark.anyio
async def test_shadow_counter_pipeline_multiple_rules(ingester: AsyncClient) -> None:
    redis = ingester._test_app.state.redis  # noqa: SLF001
    rules = [
        {
            "id": "shadow_a",
            "metadata": {"is_shadow": True},
            "when": [{"op": "is_true", "field": "is_headless"}],
        },
        {
            "id": "shadow_b",
            "metadata": {"is_shadow": True},
            "when": [{"op": "gte", "field": "device_memory", "value": 4}],
        },
        {
            "id": "not_shadow",
            "metadata": {"is_shadow": False},
            "when": [{"op": "gte", "field": "device_memory", "value": 1}],
        },
    ]
    await redis.set(SHADOW_RULES_ACTIVE_KEY, json.dumps(rules))

    sid = "dddddddd-bbbb-cccc-dddd-eeeeeeeeeeee"
    r = await ingester.post("/v1/signals/ingest", json=_valid_body(sid, dm=8))
    assert r.status_code == 201

    assert await redis.get(shadow_match_stats_key("shadow_a")) is None
    assert await redis.get(shadow_match_stats_key("shadow_b")) == "1"
    assert await redis.get(shadow_match_stats_key("not_shadow")) is None
