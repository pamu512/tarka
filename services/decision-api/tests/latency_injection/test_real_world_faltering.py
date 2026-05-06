"""Latency injection / real-world faltering: FFI slowdown, Redis partition, ML malformed JSON.

Asserts bounded latency (P99-style ceiling per request) and deterministic rule-based scores — no HTTP 500,
no indefinite hang. ML scoring failures degrade to rules-only blending (eval step SKIP).
"""

from __future__ import annotations

import asyncio
import json
import math
import os
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from pytest_mock import MockerFixture

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")

from ..aggregate_fake_redis import FakeRedis  # noqa: E402
from decision_api.aggregates import AggregateStore  # noqa: E402

# Tier-1 synchronous evaluate budget: worst-case injected FFI delay + framework overhead (tests mock upstream deps).
FFI_LATENCY_INJECTION_S = 0.5
P99_EVAL_LATENCY_CEILING_S = 2.5

# Deterministic rule engine output for FFI stub (score_delta 12 → base rule_score 22 with defaults).
_EXPECTED_RULE_DELTA = 12.0
_EXPECTED_RULE_ONLY_SCORE = 10.0 + _EXPECTED_RULE_DELTA

_RUST_STUB_RESULT: dict[str, object] = {
    "rule_hits": ["ffi_injected_latency"],
    "tags": ["ffi:slow"],
    "score_delta": _EXPECTED_RULE_DELTA,
    "contributing_pack_files": ["latency_stub.json"],
    "telemetry": [],
}


def _p99_upper_bound_ms(samples: list[float]) -> float:
    if not samples:
        return 0.0
    s = sorted(samples)
    idx = min(len(s) - 1, max(0, math.ceil(0.99 * len(s)) - 1))
    return s[idx]


async def _session_override():
    mock_session = AsyncMock()
    mock_session.add = MagicMock()
    mock_session.commit = AsyncMock()
    yield mock_session


@pytest.fixture
async def faltering_eval_client():
    """Evaluate ASGI client with ML fetch stubbed (rules-only ML path)."""
    fake = FakeRedis()
    store = AggregateStore(redis_client=fake)

    with patch("decision_api.main.init_db", new_callable=AsyncMock):
        with patch("decision_api.main.redis_tags") as mock_redis:
            mock_redis.connect = AsyncMock()
            mock_redis.close = AsyncMock()
            mock_redis._client = MagicMock()
            mock_redis.get_tags = AsyncMock(return_value=[])
            mock_redis.merge_tags = AsyncMock(return_value=["merged:tag"])
            mock_redis.set_cached_score = AsyncMock()
            mock_redis.store_nonce = AsyncMock()
            mock_redis.consume_nonce = AsyncMock(return_value=True)
            mock_redis.check_and_store_replay_signature = AsyncMock(return_value=False)
            mock_redis.check_consortium_signal = AsyncMock(return_value=None)
            mock_redis.get_tenant_flags = AsyncMock(return_value={})
            mock_redis.is_tag_store_available = True
            with patch("decision_api.main.load_rules"):
                with patch("decision_api.main.agg_store", store):
                    with patch(
                        "decision_api.main.evaluate_opa_or_raise",
                        new_callable=AsyncMock,
                        return_value=None,
                    ):
                        with patch(
                            "decision_api.main._fetch_ml_score",
                            new_callable=AsyncMock,
                            return_value=(None, {}),
                        ):
                            with patch(
                                "decision_api.main._fetch_graph_risk",
                                new_callable=AsyncMock,
                                return_value=None,
                            ):
                                with patch(
                                    "decision_api.main._get_list_store",
                                    return_value=MagicMock(
                                        check=AsyncMock(
                                            return_value=SimpleNamespace(found=False)
                                        ),
                                    ),
                                ):
                                    with patch(
                                        "decision_api.main.fingerprint_store"
                                    ) as fp:
                                        fp._client = None
                                        from decision_api.main import app, get_session

                                        app.state.http = AsyncMock()
                                        app.dependency_overrides = {}
                                        app.dependency_overrides[get_session] = (
                                            _session_override
                                        )
                                        transport = httpx.ASGITransport(app=app)
                                        async with httpx.AsyncClient(
                                            transport=transport,
                                            base_url="http://testserver",
                                            timeout=P99_EVAL_LATENCY_CEILING_S + 10.0,
                                        ) as c:
                                            c._mock_redis = mock_redis
                                            c._app = app
                                            yield c
                                        app.dependency_overrides.pop(get_session, None)


@pytest.fixture
async def faltering_eval_client_live_ml(monkeypatch):
    """Same as faltering_eval_client but uses real ``_fetch_ml_score`` (HTTP client mocked per test)."""
    monkeypatch.setenv("API_KEYS", "")
    monkeypatch.setenv("ALLOW_INSECURE_NO_AUTH", "true")
    monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    monkeypatch.setenv("FEATURE_SERVICE_URL", "")
    fake = FakeRedis()
    store = AggregateStore(redis_client=fake)

    with patch("decision_api.main.init_db", new_callable=AsyncMock):
        with patch("decision_api.main.redis_tags") as mock_redis:
            mock_redis.connect = AsyncMock()
            mock_redis.close = AsyncMock()
            mock_redis._client = MagicMock()
            mock_redis.get_tags = AsyncMock(return_value=[])
            mock_redis.merge_tags = AsyncMock(return_value=["merged:tag"])
            mock_redis.set_cached_score = AsyncMock()
            mock_redis.store_nonce = AsyncMock()
            mock_redis.consume_nonce = AsyncMock(return_value=True)
            mock_redis.check_and_store_replay_signature = AsyncMock(return_value=False)
            mock_redis.check_consortium_signal = AsyncMock(return_value=None)
            mock_redis.get_tenant_flags = AsyncMock(return_value={})
            mock_redis.is_tag_store_available = True
            with patch("decision_api.main.load_rules"):
                with patch("decision_api.main.agg_store", store):
                    with patch(
                        "decision_api.main.evaluate_opa_or_raise",
                        new_callable=AsyncMock,
                        return_value=None,
                    ):
                        with patch(
                            "decision_api.main._fetch_graph_risk",
                            new_callable=AsyncMock,
                            return_value=None,
                        ):
                            with patch(
                                "decision_api.main._get_list_store",
                                return_value=MagicMock(
                                    check=AsyncMock(
                                        return_value=SimpleNamespace(found=False)
                                    ),
                                ),
                            ):
                                with patch("decision_api.main.fingerprint_store") as fp:
                                    fp._client = None
                                    from decision_api.config import (
                                        settings as decision_settings,
                                    )
                                    from decision_api.main import app, get_session

                                    monkeypatch.setattr(
                                        decision_settings,
                                        "ml_scoring_url",
                                        "http://ml-scoring.test",
                                    )
                                    monkeypatch.setattr(
                                        decision_settings,
                                        "counter_service_url",
                                        "",
                                        raising=False,
                                    )
                                    monkeypatch.setattr(
                                        decision_settings,
                                        "location_service_url",
                                        "",
                                        raising=False,
                                    )

                                    app.state.http = AsyncMock()
                                    app.dependency_overrides = {}
                                    app.dependency_overrides[get_session] = (
                                        _session_override
                                    )
                                    transport = httpx.ASGITransport(app=app)
                                    async with httpx.AsyncClient(
                                        transport=transport,
                                        base_url="http://testserver",
                                        timeout=P99_EVAL_LATENCY_CEILING_S + 10.0,
                                    ) as c:
                                        c._mock_redis = mock_redis
                                        c._app = app
                                        yield c
                                    app.dependency_overrides.pop(get_session, None)


def _stub_rust_eval_slow(*_a: object, **_k: object) -> dict[str, object]:
    time.sleep(FFI_LATENCY_INJECTION_S)
    return dict(_RUST_STUB_RESULT)


@pytest.mark.asyncio
async def test_slow_rust_ffi_returns_200_rule_score_under_p99_ceiling(
    faltering_eval_client: httpx.AsyncClient,
    mocker: MockerFixture,
) -> None:
    """Inject ~500ms into the Rust FFI boundary; response remains 200 with deterministic rule-only score."""
    mocker.patch(
        "decision_api.rust_rule_engine_ffi.should_use_rust_json_engine",
        return_value=True,
    )
    mocker.patch(
        "decision_api.rust_rule_engine_ffi.evaluate_cached_packs_via_rust",
        side_effect=_stub_rust_eval_slow,
    )

    body = {
        "tenant_id": "lat_tenant",
        "event_type": "payment",
        "entity_id": "lat_entity",
        "payload": {"amount": 10.0},
    }
    t0 = time.perf_counter()
    r = await faltering_eval_client.post("/v1/decisions/evaluate", json=body)
    elapsed = time.perf_counter() - t0

    assert r.status_code == 200
    data = r.json()
    assert data["decision"] == "allow"
    assert pytest.approx(data["score"], rel=1e-6, abs=1e-6) == _EXPECTED_RULE_ONLY_SCORE
    assert elapsed < P99_EVAL_LATENCY_CEILING_S

    samples_ms: list[float] = []
    for _ in range(10):
        t1 = time.perf_counter()
        rr = await faltering_eval_client.post("/v1/decisions/evaluate", json=body)
        samples_ms.append((time.perf_counter() - t1) * 1000.0)
        assert rr.status_code == 200
        assert (
            pytest.approx(rr.json()["score"], rel=1e-5, abs=1e-5)
            == _EXPECTED_RULE_ONLY_SCORE
        )

    assert _p99_upper_bound_ms(samples_ms) / 1000.0 < P99_EVAL_LATENCY_CEILING_S


@pytest.mark.asyncio
async def test_redis_cluster_drop_evaluate_degrades_without_500(
    faltering_eval_client: httpx.AsyncClient,
    mocker: MockerFixture,
) -> None:
    """Simulate Redis cluster connection loss during merge_tags; evaluate completes with deterministic score."""

    async def boom_merge(*_a: object, **_k: object) -> None:
        from redis.exceptions import ConnectionError as RedisConnectionError

        raise RedisConnectionError("connection dropped")

    faltering_eval_client._mock_redis.merge_tags = AsyncMock(side_effect=boom_merge)

    mocker.patch(
        "decision_api.rust_rule_engine_ffi.should_use_rust_json_engine",
        return_value=True,
    )
    mocker.patch(
        "decision_api.rust_rule_engine_ffi.evaluate_cached_packs_via_rust",
        return_value=dict(_RUST_STUB_RESULT),
    )

    body = {
        "tenant_id": "redis_drop",
        "event_type": "payment",
        "entity_id": "e1",
        "payload": {},
    }
    r = await asyncio.wait_for(
        faltering_eval_client.post("/v1/decisions/evaluate", json=body),
        timeout=P99_EVAL_LATENCY_CEILING_S,
    )
    assert r.status_code == 200
    data = r.json()
    assert pytest.approx(data["score"], rel=1e-6, abs=1e-6) == _EXPECTED_RULE_ONLY_SCORE
    assert "redis:tag_merge_unavailable" in data["tags"]


@pytest.mark.asyncio
async def test_ml_upstream_malformed_json_rules_only_score(
    faltering_eval_client_live_ml: httpx.AsyncClient,
    mocker: MockerFixture,
) -> None:
    """Malformed JSON from ML scoring HTTP upstream → ML step skips; deterministic rules-only score."""

    async def post_impl(url: str, **_kwargs: object):
        if "/v1/score" in str(url):
            resp = MagicMock()
            resp.status_code = 200
            resp.raise_for_status = MagicMock()

            async def bad_json() -> dict[str, object]:
                raise json.JSONDecodeError("malformed", "not-json{{{", 0)

            resp.json = bad_json
            return resp
        return MagicMock(
            status_code=200,
            raise_for_status=MagicMock(),
            json=AsyncMock(return_value={}),
        )

    faltering_eval_client_live_ml._app.state.http.post = AsyncMock(
        side_effect=post_impl
    )

    mocker.patch(
        "decision_api.main.EvalDAGRuntime.include_ml",
        lambda self, _trace: True,
    )

    mocker.patch(
        "decision_api.rust_rule_engine_ffi.should_use_rust_json_engine",
        return_value=True,
    )
    mocker.patch(
        "decision_api.rust_rule_engine_ffi.evaluate_cached_packs_via_rust",
        return_value=dict(_RUST_STUB_RESULT),
    )

    body = {
        "tenant_id": "ml_bad_json",
        "event_type": "payment",
        "entity_id": "e2",
        "payload": {},
    }
    r = await asyncio.wait_for(
        faltering_eval_client_live_ml.post("/v1/decisions/evaluate", json=body),
        timeout=P99_EVAL_LATENCY_CEILING_S,
    )
    assert r.status_code == 200
    data = r.json()
    assert data["ml_score"] is None
    assert pytest.approx(data["score"], rel=1e-6, abs=1e-6) == _EXPECTED_RULE_ONLY_SCORE


@pytest.fixture(autouse=True)
def _latency_env(monkeypatch):
    monkeypatch.setenv("API_KEYS", "")
    monkeypatch.setenv("ALLOW_INSECURE_NO_AUTH", "true")
    monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    monkeypatch.setenv("FEATURE_SERVICE_URL", "")
