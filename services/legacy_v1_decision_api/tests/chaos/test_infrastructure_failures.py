"""Chaos-style integration tests: failures injected only at FFI / Redis boundaries.

Internal circuit-breaker, merge logic, and KV fallback paths run unmocked.
"""

from __future__ import annotations

import asyncio
import types

import pytest
from pytest_mock import MockerFixture

from decision_api.config import settings
from decision_api.redis_store import RedisTags
from decision_api.rust_ffi_circuit import (
    circuit_is_open,
    failures_in_window,
    record_rust_ffi_success,
)
from decision_api.rust_rule_engine_exceptions import (
    RustRuleEngineCircuitOpenError,
    RustRuleEngineInvocationFailed,
)
from decision_api.rust_rule_engine_ffi import evaluate_json_rules_via_rust
from tarka_core.cache import LocalDictCache


def test_rust_ffi_burst_trips_sliding_window_circuit(
    mocker: MockerFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Simulate repeated RuntimeError from PyO3 (boundary); assert real FFI circuit opens."""
    monkeypatch.setattr(
        "decision_api.rust_ffi_circuit.settings.rust_ffi_circuit_failure_threshold",
        5,
        raising=False,
    )
    monkeypatch.setattr(
        "decision_api.rust_ffi_circuit.settings.rust_ffi_circuit_window_seconds",
        120.0,
        raising=False,
    )
    record_rust_ffi_success()
    assert circuit_is_open() is False

    fake_rust = types.SimpleNamespace()
    ffi_calls = {"n": 0}

    def evaluate_adhoc_packs_rust(*_a: object, **_k: object) -> str:
        ffi_calls["n"] += 1
        raise RuntimeError("simulated tarka_rule_engine fault under burst load")

    fake_rust.evaluate_adhoc_packs_rust = evaluate_adhoc_packs_rust
    fake_rust.evaluate_json_rules_rust = evaluate_adhoc_packs_rust
    fake_rust.sync_packs_json = lambda _j: None

    mocker.patch("decision_api.rust_rule_engine_ffi._rust", return_value=fake_rust)

    packs = [{"pack_id": "chaos", "rules": [], "_source_file": "chaos.json"}]
    for _ in range(5):
        with pytest.raises(RustRuleEngineInvocationFailed):
            evaluate_json_rules_via_rust(packs, {}, [], "tenant", "entity")

    assert ffi_calls["n"] == 5
    assert failures_in_window() >= 5
    assert circuit_is_open() is True

    with pytest.raises(RustRuleEngineCircuitOpenError):
        evaluate_json_rules_via_rust(packs, {}, [], "tenant", "entity")

    assert ffi_calls["n"] == 5

    record_rust_ffi_success()


@pytest.mark.asyncio
async def test_partitioned_redis_slow_merge_fails_over_to_local_kv(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    """Redis responds but > deadline (partition / latency); assert failover to reserved LocalDictCache."""

    monkeypatch.setenv("REDIS_MERGE_TIMEOUT_SECONDS", "0.2")
    monkeypatch.setenv("TARKA_KV_FALLBACK_LOCK_PATH", str(tmp_path / "chaos_kv.lock"))
    monkeypatch.setattr(settings, "strict_consistency", False, raising=False)

    kv = LocalDictCache()
    store = RedisTags("")
    store._fallback_lock_path = tmp_path / "chaos_kv.lock"
    store._kv_degraded = kv

    evalsha_calls = {"n": 0}

    async def slow_evalsha(*_a: object, **_k: object) -> str:
        evalsha_calls["n"] += 1
        await asyncio.sleep(0.25)
        return '["should_not_win"]'

    class _FakeRedis:
        async def aclose(self) -> None:
            return None

    fake = _FakeRedis()
    fake.evalsha = slow_evalsha  # type: ignore[method-assign]
    store._client = fake  # type: ignore[assignment]
    store._merge_sha = "deadbeefcafe"

    merged = await store.merge_tags("acme", "user-1", ["partition:failover"])
    assert "partition:failover" in merged
    assert evalsha_calls["n"] == 1
    assert store.has_remote_redis is False
    assert store._kv is kv

    roundtrip = await store.get_tags("acme", "user-1")
    assert sorted(roundtrip) == sorted(merged)

    await store.close()


@pytest.mark.asyncio
async def test_strict_consistency_merge_timeout_does_not_failover(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    monkeypatch.setenv("REDIS_MERGE_TIMEOUT_SECONDS", "0.15")
    monkeypatch.setenv("TARKA_KV_FALLBACK_LOCK_PATH", str(tmp_path / "strict.lock"))
    monkeypatch.setattr(settings, "strict_consistency", True, raising=False)

    kv = LocalDictCache()
    store = RedisTags("")
    store._fallback_lock_path = tmp_path / "strict.lock"
    store._kv_degraded = kv

    async def slow_evalsha(*_a: object, **_k: object) -> str:
        await asyncio.sleep(0.3)
        return "[]"

    class _FakeRedis:
        async def aclose(self) -> None:
            return None

    fake = _FakeRedis()
    fake.evalsha = slow_evalsha  # type: ignore[method-assign]
    store._client = fake  # type: ignore[assignment]
    store._merge_sha = "sha"

    with pytest.raises(ConnectionError, match="STRICT_CONSISTENCY"):
        await store.merge_tags("t", "e", ["x"])

    assert store.has_remote_redis is True
    await store.close()
