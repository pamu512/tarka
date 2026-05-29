"""Gate: evaluate DAG tenant lookup fail-closed and non-critical metrics degraded."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]
_DECISION_SRC = _REPO_ROOT / "services/decision-api/src"
_SHARED = _REPO_ROOT / "services/shared"
for _p in (_DECISION_SRC, _SHARED):
    _token = str(_p)
    if _token not in sys.path:
        sys.path.insert(0, _token)

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("API_KEYS", "test-key")

from decision_api.main import TENANT_CONFIG_UNAVAILABLE_DETAIL  # noqa: E402

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def _patch_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("API_KEYS", "test-key")
    monkeypatch.delenv("ALLOW_INSECURE_NO_AUTH", raising=False)
    monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    monkeypatch.setenv("FEATURE_SERVICE_URL", "")


@pytest.fixture
async def evaluate_client():
    with patch("decision_api.main.init_db", new_callable=AsyncMock):
        with patch("decision_api.main.redis_tags") as mock_redis:
            mock_redis.connect = AsyncMock()
            mock_redis.close = AsyncMock()
            mock_redis._client = MagicMock()
            mock_redis.is_tag_store_available = True
            mock_redis.get_tags = AsyncMock(return_value=[])
            mock_redis.merge_tags = AsyncMock(return_value=["sdk:vpn"])
            mock_redis.set_cached_score = AsyncMock()
            mock_redis.store_nonce = AsyncMock()
            mock_redis.consume_nonce = AsyncMock(return_value=True)
            mock_redis.check_and_store_replay_signature = AsyncMock(return_value=False)
            mock_redis.get_tenant_flags = AsyncMock(return_value={})

            with patch("decision_api.main.load_rules"):
                with patch("decision_api.main.agg_store") as mock_agg:
                    mock_agg._client = None
                    from decision_api.main import app

                    app.state.http = AsyncMock()
                    app.dependency_overrides = {}
                    transport = httpx.ASGITransport(app=app)
                    async with httpx.AsyncClient(
                        transport=transport,
                        base_url="http://testserver",
                        headers={"x-api-key": "test-key"},
                    ) as client:
                        client.tarka_app = app  # type: ignore[attr-defined]
                        client.mock_redis = mock_redis  # type: ignore[attr-defined]
                        yield client
                    app.dependency_overrides = {}


def _override_session_factory(mock_session: AsyncMock):
    async def _override():
        yield mock_session

    return _override


def _evaluate_payload() -> dict:
    return {
        "tenant_id": "tenant-dag-gate",
        "event_type": "login",
        "entity_id": "entity-1",
        "payload": {},
    }


@pytest.mark.asyncio
async def test_evaluation_fails_closed_on_missing_tenant(evaluate_client: httpx.AsyncClient) -> None:
    evaluate_client.mock_redis.get_tenant_flags = AsyncMock(  # type: ignore[attr-defined]
        side_effect=RuntimeError("redis unavailable"),
    )
    r = await evaluate_client.post("/v1/decisions/evaluate", json=_evaluate_payload())
    assert r.status_code == 500
    assert r.json()["detail"] == TENANT_CONFIG_UNAVAILABLE_DETAIL


@pytest.mark.asyncio
async def test_evaluation_succeeds_degraded_on_metric_failure(
    evaluate_client: httpx.AsyncClient,
    caplog: pytest.LogCaptureFixture,
) -> None:
    mock_session = AsyncMock()
    mock_session.add = MagicMock()
    mock_session.commit = AsyncMock()
    from decision_api.main import get_session

    mock_metrics = MagicMock()

    def _inc_raises(metric: str) -> None:
        if metric == "fraud_evaluations_total":
            raise RuntimeError("metrics backend unavailable")

    mock_metrics.inc = MagicMock(side_effect=_inc_raises)

    with caplog.at_level("WARNING"):
        with patch("decision_api.main.get_metrics", return_value=mock_metrics):
            with patch(
                "decision_api.main.evaluate_json_rules",
                return_value=([], [], 0.0, []),
            ):
                with patch(
                    "decision_api.main.evaluate_opa_or_raise",
                    new_callable=AsyncMock,
                    return_value=None,
                ):
                    with patch(
                        "decision_api.main._fetch_ml_score_wrapped",
                        new_callable=AsyncMock,
                        return_value=(None, {}),
                    ):
                        evaluate_client.tarka_app.dependency_overrides[get_session] = (  # type: ignore[attr-defined]
                            _override_session_factory(mock_session)
                        )
                        r = await evaluate_client.post(
                            "/v1/decisions/evaluate",
                            json=_evaluate_payload(),
                        )
                        evaluate_client.tarka_app.dependency_overrides.pop(  # type: ignore[attr-defined]
                            get_session,
                            None,
                        )

    assert r.status_code == 200
    assert r.json()["decision"] == "allow"
    assert any(
        "decision_metrics_inc_failed" in rec.message and "fraud_evaluations_total" in rec.message
        for rec in caplog.records
    )
