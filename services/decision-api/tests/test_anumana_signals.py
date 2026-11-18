"""Anumana velocity/risk signals read into evaluate features."""

from __future__ import annotations

import asyncio
from typing import Any

from decision_api.anumana_signals import (
    ANUMANA_VEL_PREFIX,
    anumana_device_token,
    anumana_velocity_features,
    merge_anumana_signals,
    session_risk_key,
)


def asyncio_run(coro):
    return asyncio.get_event_loop_policy().new_event_loop().run_until_complete(coro)


def test_anumana_velocity_reads_aggregate_store_device_key() -> None:
    import hashlib

    class _Store:
        def __init__(self) -> None:
            self.keys: list[tuple] = []

        async def count(self, tenant_id, entity_id, window_seconds):
            self.keys.append((tenant_id, entity_id, window_seconds))
            return {60: 2, 300: 0, 3600: 4}[window_seconds]

    store = _Store()
    feats = asyncio_run(
        anumana_velocity_features(
            store, tenant_id="acme", canvas="fp-canvas-abc", now_unix=1
        )
    )
    token = hashlib.sha256(b"fp-canvas-abc").hexdigest()
    assert feats == {"anumana_velocity_1m": 2, "anumana_velocity_1h": 4}
    assert ("acme", f"device:{token}", 60) in store.keys


def test_prefix() -> None:
    assert ANUMANA_VEL_PREFIX == "anumana:velocity"


def test_device_token_matches_orchestrator_derivation() -> None:
    import hashlib

    canvas = " fp-canvas-abc "
    assert anumana_device_token(canvas) == hashlib.sha256(b"fp-canvas-abc").hexdigest()
    assert anumana_device_token("") is None
    assert anumana_device_token(None) is None


class _FakeRedis:
    def __init__(self, counts: list[int] | None = None, mapping: dict[str, str] | None = None) -> None:
        self.counts = list(counts or [])
        self.mapping = mapping or {}
        self.get_calls: list[str] = []

    async def zcount(self, key: str, cutoff: float, hi: str) -> int:
        del key, cutoff, hi
        if not self.counts:
            return 0
        return self.counts.pop(0)

    async def get(self, key: str) -> str | None:
        self.get_calls.append(key)
        return self.mapping.get(key)


def test_velocity_missing_keys_absent() -> None:
    r = _FakeRedis(counts=[0, 0, 0])
    feats = asyncio_run(
        anumana_velocity_features(r, tenant_id="t1", canvas="fp-canvas-abc", now_unix=1)
    )
    assert feats == {}


def test_velocity_redis_error_fail_open() -> None:
    class _Boom:
        async def count(self, tenant_id, entity_id, window_seconds):
            raise ConnectionError("down")

    feats = asyncio_run(
        anumana_velocity_features(_Boom(), tenant_id="t1", canvas="fp", now_unix=1)
    )
    assert feats == {}


def test_session_risk_key_format_exact() -> None:
    k = session_risk_key("t1", "sess-9")
    assert k == "anumana:session_risk:t1\x1fsess-9"


def test_merge_sets_dropoff_and_tags() -> None:
    r = _FakeRedis(counts=[0, 0, 4])
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
