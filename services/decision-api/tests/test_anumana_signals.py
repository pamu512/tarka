"""Anumana velocity/risk signals read into evaluate features."""

from __future__ import annotations

import hashlib
import asyncio
from typing import Any

import pytest


def asyncio_run(coro):
    return asyncio.get_event_loop_policy().new_event_loop().run_until_complete(coro)

from decision_api.anumana_signals import (
    ANUMANA_VEL_PREFIX,
    anumana_device_token,
    anumana_velocity_features,
    merge_anumana_signals,
    session_risk_key,
)


def test_prefix() -> None:
    assert ANUMANA_VEL_PREFIX == "anumana:velocity"


def test_device_token_matches_orchestrator_derivation() -> None:
    import hashlib

    canvas = " fp-canvas-abc "
    assert anumana_device_token(canvas) == hashlib.sha256(b"fp-canvas-abc").hexdigest()
    assert anumana_device_token("") is None
    assert anumana_device_token(None) is None


class _FakeRedis:
    def __init__(self, mapping: dict[str, str] | None = None) -> None:
        self.mapping = mapping or {}
        self.get_calls: list[str] = []

    async def mget(self, keys: list[str]) -> list[str | None]:
        return [self.mapping.get(k) for k in keys]

    async def get(self, key: str) -> str | None:
        self.get_calls.append(key)
        return self.mapping.get(key)


def test_velocity_key_format_exact() -> None:
    r = _FakeRedis()
    token = anumana_device_token("fp-canvas-abc")
    now = 1_700_000_000
    key_1m = f"{ANUMANA_VEL_PREFIX}:t:t1:device:1m:{token}:{now // 60}"
    r.mapping[key_1m] = "7"
    feats = asyncio_run(
        anumana_velocity_features(r, tenant_id="t1", canvas="fp-canvas-abc", now_unix=now)
    )
    assert feats == {"anumana_velocity_1m": 7}


def test_velocity_missing_keys_absent() -> None:
    r = _FakeRedis()
    feats = asyncio_run(
        anumana_velocity_features(r, tenant_id="t1", canvas="fp-canvas-abc", now_unix=1)
    )
    assert feats == {}


def test_velocity_redis_error_fail_open() -> None:
    class _Boom:
        async def mget(self, keys: list[str]) -> list[str | None]:
            raise ConnectionError("down")

    feats = asyncio_run(
        anumana_velocity_features(_Boom(), tenant_id="t1", canvas="fp", now_unix=1)
    )
    assert feats == {}


def test_session_risk_key_format_exact() -> None:
    k = session_risk_key("t1", "sess-9")
    assert k == "anumana:session_risk:t1\x1fsess-9"


def test_merge_sets_dropoff_and_tags() -> None:
    r = _FakeRedis()
    token = anumana_device_token("fp")
    now = 1_700_000_000
    r.mapping[f"{ANUMANA_VEL_PREFIX}:t:t1:device:1h:{token}:{now // 3600}"] = "4"
    r.mapping[session_risk_key("t1", "sess-9")] = "HIGH_RISK_DROPOFF"
    feats: dict[str, Any] = {}
    tags: list[str] = []
    asyncio_run(
        merge_anumana_signals(
            r,
            tenant_id="t1",
            canvas="fp",
            session_id="sess-9",
            features=feats,
            degrade_tags=tags,
            now_unix=now,
        )
    )
    assert feats["anumana_velocity_1h"] == 4
    assert feats["session_dropoff_risk"] is True
    assert "sdk:anumana_velocity" in tags
    assert "sdk:session_dropoff" in tags


def test_merge_none_redis_noop() -> None:
    feats: dict[str, Any] = {}
    asyncio_run(
        merge_anumana_signals(
            None, tenant_id="t1", canvas="fp", session_id=None, features=feats
        )
    )
    assert feats == {}
