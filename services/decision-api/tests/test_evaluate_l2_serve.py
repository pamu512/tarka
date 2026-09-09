"""G1.3: evaluate reads L2 when FEATURE_STORE_URL is set; miss/timeout fail-soft."""

from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("API_KEYS", "test-key")

_REPO = Path(__file__).resolve().parents[3]
for _p in (
    _REPO / "services/decision-api/src",
    _REPO / "services/shared",
    _REPO / "packages/shared-core",
    _REPO / "services/analytics/src",
):
    _s = str(_p)
    if _s not in sys.path:
        sys.path.insert(0, _s)

from decision_api.feature_l2 import (  # noqa: E402
    _STORE,
    evaluate_l2_read,
    fetch_l2_features,
    get_features,
    serve_features,
)


def _override_session_factory(mock_session):
    async def _override():
        yield mock_session

    return _override


def _eval_body(**extra: object) -> dict:
    body: dict = {
        "tenant_id": "t-l2",
        "event_type": "payment",
        "entity_id": "u-l2",
        "role": "member",
        "payload": {"amount": 10},
    }
    body.update(extra)
    return body


@pytest.fixture
async def eval_client(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("API_KEYS", "test-key")
    monkeypatch.delenv("ALLOW_INSECURE_NO_AUTH", raising=False)
    monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    monkeypatch.setenv("FEATURE_SERVICE_URL", "")
    monkeypatch.delenv("VENDOR_SCORE_URL", raising=False)
    monkeypatch.setenv("GRAPH_SERVICE_URL", "")

    main = importlib.import_module("decision_api.main")
    with patch.object(main, "init_db", new_callable=AsyncMock):
        with patch.object(main, "redis_tags") as mock_redis:
            mock_redis.connect = AsyncMock()
            mock_redis.close = AsyncMock()
            mock_redis._client = MagicMock()
            mock_redis.get_tags = AsyncMock(return_value=[])
            mock_redis.merge_tags = AsyncMock(return_value=[])
            mock_redis.set_cached_score = AsyncMock()
            mock_redis.store_nonce = AsyncMock()
            mock_redis.consume_nonce = AsyncMock(return_value=True)
            mock_redis.check_and_store_replay_signature = AsyncMock(return_value=False)
            mock_redis.get_tenant_flags = AsyncMock(return_value={})
            with patch.object(main, "load_rules"):
                with patch.object(main, "agg_store") as mock_agg:
                    mock_agg._client = None
                    app = main.app
                    mock_session = AsyncMock()
                    mock_session.add = MagicMock()
                    mock_session.commit = AsyncMock()
                    app.state.http = AsyncMock()
                    app.dependency_overrides[main.get_session] = (
                        _override_session_factory(mock_session)
                    )
                    transport = httpx.ASGITransport(app=app)
                    async with httpx.AsyncClient(
                        transport=transport, base_url="http://testserver"
                    ) as client:
                        client.headers.update({"x-api-key": "test-key"})
                        client.tarka_app = app  # type: ignore[attr-defined]
                        client.tarka_main = main  # type: ignore[attr-defined]
                        yield client
                    app.dependency_overrides.pop(main.get_session, None)


def _feature_gets(http: AsyncMock) -> list[tuple[str, dict]]:
    out: list[tuple[str, dict]] = []
    for call in http.get.await_args_list:
        url = str(call.args[0]) if call.args else str(call.kwargs.get("url") or "")
        if "/v1/features" in url:
            out.append((url, dict(call.kwargs)))
    return out


@pytest.mark.asyncio
async def test_fetch_l2_empty_url_never_calls_http(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FEATURE_STORE_URL", "")
    http = AsyncMock()
    out = await fetch_l2_features(
        http, tenant_id="t-l2", entity_id="u-l2", as_of="2026-03-01T12:00:00Z"
    )
    assert out is None
    http.get.assert_not_called()


@pytest.mark.asyncio
async def test_evaluate_l2_read_empty_url_is_l1_or_raw(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FEATURE_STORE_URL", "")
    http = AsyncMock()
    feats, source = await evaluate_l2_read(
        http,
        tenant_id="t-l2",
        entity_id="u-l2",
        as_of="2026-03-01T12:00:00Z",
        redis_url="redis://localhost:6379/0",
    )
    assert feats is None
    assert source in {"l1", "raw"}
    assert source != "l2"
    http.get.assert_not_called()


@pytest.mark.asyncio
async def test_evaluate_l2_read_hit_is_l2(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FEATURE_STORE_URL", "http://fs.test")
    as_of = "2026-03-01T12:00:00Z"

    async def _get(url, **kwargs):
        return SimpleNamespace(
            status_code=200,
            json=lambda: {"features": {"event_count_1h": 4}},
        )

    http = AsyncMock()
    http.get = AsyncMock(side_effect=_get)
    feats, source = await evaluate_l2_read(
        http,
        tenant_id="t-l2",
        entity_id="u-l2",
        as_of=as_of,
        redis_url="redis://localhost:6379/0",
    )
    assert source == "l2"
    assert feats == {"event_count_1h": 4}
    http.get.assert_awaited()
    url = str(http.get.await_args.args[0])
    params = http.get.await_args.kwargs.get("params") or {}
    assert "/v1/features/user/u-l2" in url
    assert params.get("tenant_id") == "t-l2"
    assert params.get("as_of") == as_of


@pytest.mark.asyncio
async def test_evaluate_l2_read_timeout_falls_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FEATURE_STORE_URL", "http://fs.test")

    http = AsyncMock()
    http.get = AsyncMock(side_effect=TimeoutError("l2 slow"))
    feats, source = await evaluate_l2_read(
        http,
        tenant_id="t-l2",
        entity_id="u-l2",
        as_of="2026-03-01T12:00:00Z",
        redis_url="redis://localhost:6379/0",
    )
    assert feats is None
    assert source in {"l1", "raw"}
    assert source != "l2"


@pytest.mark.asyncio
async def test_evaluate_l2_read_miss_falls_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FEATURE_STORE_URL", "http://fs.test")

    async def _miss(url, **kwargs):
        return SimpleNamespace(status_code=200, json=lambda: {"features": {}})

    http = AsyncMock()
    http.get = AsyncMock(side_effect=_miss)
    feats, source = await evaluate_l2_read(
        http,
        tenant_id="t-l2",
        entity_id="u-l2",
        as_of="2026-03-01T12:00:00Z",
        redis_url="redis://localhost:6379/0",
    )
    assert feats is None
    assert source in {"l1", "raw"}
    assert source != "l2"


def test_pipeline_calls_evaluate_l2_read() -> None:
    text = (
        Path(__file__).resolve().parents[1] / "src/decision_api/evaluate/pipeline.py"
    ).read_text(encoding="utf-8")
    assert "evaluate_l2_read" in text


@pytest.mark.asyncio
async def test_evaluate_empty_feature_store_url_never_calls_l2(
    eval_client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("FEATURE_STORE_URL", raising=False)
    monkeypatch.setenv("FEATURE_STORE_URL", "")
    main = eval_client.tarka_main  # type: ignore[attr-defined]
    with (
        patch.object(main, "evaluate_json_rules", return_value=([], [], 0.0, [])),
        patch.object(
            main,
            "evaluate_opa_or_raise",
            new_callable=AsyncMock,
            return_value=None,
        ),
        patch.object(
            main,
            "_fetch_ml_score_wrapped",
            new_callable=AsyncMock,
            return_value=(None, {}),
        ),
    ):
        r = await eval_client.post("/v1/decisions/evaluate", json=_eval_body())
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["decision"]
    assert data["feature_source"] in {"l1", "raw"}
    assert data["feature_source"] != "l2"
    assert _feature_gets(eval_client.tarka_app.state.http) == []


@pytest.mark.asyncio
async def test_evaluate_reads_l2_with_as_of_when_url_set(
    eval_client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FEATURE_STORE_URL", "http://fs.test")
    as_of = "2026-03-01T12:00:00Z"

    async def _get(url, **kwargs):
        payload = {
            "feature_source": "l2",
            "features": {"event_count_1h": 4},
            "as_of": as_of,
        }
        return SimpleNamespace(status_code=200, json=lambda: payload)

    eval_client.tarka_app.state.http.get = AsyncMock(side_effect=_get)
    main = eval_client.tarka_main  # type: ignore[attr-defined]
    with (
        patch.object(main, "evaluate_json_rules", return_value=([], [], 0.0, [])),
        patch.object(
            main,
            "evaluate_opa_or_raise",
            new_callable=AsyncMock,
            return_value=None,
        ),
        patch.object(
            main,
            "_fetch_ml_score_wrapped",
            new_callable=AsyncMock,
            return_value=(None, {}),
        ),
    ):
        r = await eval_client.post(
            "/v1/decisions/evaluate",
            json=_eval_body(metadata={"event_time": as_of}),
        )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["feature_source"] == "l2"
    gets = _feature_gets(eval_client.tarka_app.state.http)
    assert gets, "evaluate must GET L2 when FEATURE_STORE_URL is set"
    url, kwargs = gets[0]
    assert "/v1/features/user/u-l2" in url
    params = kwargs.get("params") or {}
    assert params.get("tenant_id") == "t-l2"
    assert params.get("as_of") == as_of


@pytest.mark.asyncio
async def test_evaluate_l2_timeout_fail_soft_not_fake_l2(
    eval_client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FEATURE_STORE_URL", "http://fs.test")

    async def _timeout(*_a, **_k):
        raise TimeoutError("l2 slow")

    eval_client.tarka_app.state.http.get = AsyncMock(side_effect=_timeout)
    main = eval_client.tarka_main  # type: ignore[attr-defined]
    with (
        patch.object(main, "evaluate_json_rules", return_value=([], [], 0.0, [])),
        patch.object(
            main,
            "evaluate_opa_or_raise",
            new_callable=AsyncMock,
            return_value=None,
        ),
        patch.object(
            main,
            "_fetch_ml_score_wrapped",
            new_callable=AsyncMock,
            return_value=(None, {}),
        ),
    ):
        r = await eval_client.post("/v1/decisions/evaluate", json=_eval_body())
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["decision"]
    assert data["feature_source"] in {"l1", "raw"}
    assert data["feature_source"] != "l2"


@pytest.mark.asyncio
async def test_evaluate_l2_miss_fail_soft_not_fake_l2(
    eval_client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FEATURE_STORE_URL", "http://fs.test")

    async def _miss(url, **kwargs):
        return SimpleNamespace(status_code=200, json=lambda: {"features": {}})

    eval_client.tarka_app.state.http.get = AsyncMock(side_effect=_miss)
    main = eval_client.tarka_main  # type: ignore[attr-defined]
    with (
        patch.object(main, "evaluate_json_rules", return_value=([], [], 0.0, [])),
        patch.object(
            main,
            "evaluate_opa_or_raise",
            new_callable=AsyncMock,
            return_value=None,
        ),
        patch.object(
            main,
            "_fetch_ml_score_wrapped",
            new_callable=AsyncMock,
            return_value=(None, {}),
        ),
    ):
        r = await eval_client.post("/v1/decisions/evaluate", json=_eval_body())
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["decision"]
    assert data["feature_source"] in {"l1", "raw"}
    assert data["feature_source"] != "l2"


@pytest.mark.asyncio
async def test_evaluate_seen_event_readable_at_as_of_no_later_leak(
    eval_client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FEATURE_STORE_URL", "http://fs.test")
    tenant, entity = "t-w-eval-pit", "u-w-eval-pit"
    _STORE.pop((tenant, "user", entity), None)
    t1 = "2026-01-01T00:00:00Z"
    t2 = "2026-06-01T00:00:00Z"
    main = eval_client.tarka_main  # type: ignore[attr-defined]
    with (
        patch.object(main, "evaluate_json_rules", return_value=([], [], 0.0, [])),
        patch.object(
            main,
            "evaluate_opa_or_raise",
            new_callable=AsyncMock,
            return_value=None,
        ),
        patch.object(
            main,
            "_fetch_ml_score_wrapped",
            new_callable=AsyncMock,
            return_value=(None, {}),
        ),
    ):
        r1 = await eval_client.post(
            "/v1/decisions/evaluate",
            json=_eval_body(
                tenant_id=tenant,
                entity_id=entity,
                payload={"amount": 10},
                metadata={"event_time": t1},
            ),
        )
        r2 = await eval_client.post(
            "/v1/decisions/evaluate",
            json=_eval_body(
                tenant_id=tenant,
                entity_id=entity,
                payload={"amount": 99},
                metadata={"event_time": t2},
            ),
        )
    assert r1.status_code == 200, r1.text
    assert r2.status_code == 200, r2.text
    assert (
        get_features(
            tenant_id=tenant, entity_type="user", entity_id=entity, as_of=t1
        ).get("amount")
        == 10
    )
    assert (
        get_features(
            tenant_id=tenant,
            entity_type="user",
            entity_id=entity,
            as_of="2025-12-01T00:00:00Z",
        )
        == {}
    )
    assert (
        get_features(
            tenant_id=tenant, entity_type="user", entity_id=entity, as_of=t2
        ).get("amount")
        == 99
    )


@pytest.mark.asyncio
async def test_evaluate_empty_url_writer_noop_serve_stays_off(
    eval_client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("FEATURE_STORE_URL", raising=False)
    monkeypatch.setenv("FEATURE_STORE_URL", "")
    tenant, entity = "t-w-eval-off", "u-w-eval-off"
    _STORE.pop((tenant, "user", entity), None)
    main = eval_client.tarka_main  # type: ignore[attr-defined]
    with (
        patch.object(main, "evaluate_json_rules", return_value=([], [], 0.0, [])),
        patch.object(
            main,
            "evaluate_opa_or_raise",
            new_callable=AsyncMock,
            return_value=None,
        ),
        patch.object(
            main,
            "_fetch_ml_score_wrapped",
            new_callable=AsyncMock,
            return_value=(None, {}),
        ),
    ):
        r = await eval_client.post(
            "/v1/decisions/evaluate",
            json=_eval_body(
                tenant_id=tenant,
                entity_id=entity,
                payload={"amount": 10, "created_at": "2026-01-01T00:00:00Z"},
            ),
        )
    assert r.status_code == 200, r.text
    assert r.json()["decision"]
    assert (tenant, "user", entity) not in _STORE
    assert (
        get_features(
            tenant_id=tenant,
            entity_type="user",
            entity_id=entity,
            as_of="2026-01-01T00:00:00Z",
        )
        == {}
    )
    served = await serve_features("user", entity, tenant_id=tenant)
    assert served["l2"] == "off"
    assert served["feature_source"] != "l2"


@pytest.mark.asyncio
async def test_evaluate_writer_exception_fail_soft(
    eval_client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FEATURE_STORE_URL", "http://fs.test")
    main = eval_client.tarka_main  # type: ignore[attr-defined]
    with (
        patch.object(main, "evaluate_json_rules", return_value=([], [], 0.0, [])),
        patch.object(
            main,
            "evaluate_opa_or_raise",
            new_callable=AsyncMock,
            return_value=None,
        ),
        patch.object(
            main,
            "_fetch_ml_score_wrapped",
            new_callable=AsyncMock,
            return_value=(None, {}),
        ),
        patch(
            "decision_api.evaluate.pipeline.write_event_features",
            side_effect=RuntimeError("writer lag"),
        ),
    ):
        r = await eval_client.post("/v1/decisions/evaluate", json=_eval_body())
    assert r.status_code == 200, r.text
    assert r.json()["decision"]
