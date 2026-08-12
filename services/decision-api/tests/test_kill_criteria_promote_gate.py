"""Promote/activate must refuse when kill_criteria fire."""

from __future__ import annotations

import os
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")

from decision_api.vertical_packs import evaluate_kill_criteria


@pytest.fixture(autouse=True)
def _patch_env(monkeypatch):
    monkeypatch.setenv("API_KEYS", "test-key")
    monkeypatch.delenv("ALLOW_INSECURE_NO_AUTH", raising=False)
    monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    monkeypatch.setenv("FEATURE_SERVICE_URL", "")


@pytest.fixture
async def client():
    with patch("decision_api.main.init_db", new_callable=AsyncMock):
        with patch("decision_api.main.redis_tags") as mock_redis:
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

            with patch("decision_api.main.load_rules"):
                with patch("decision_api.main.agg_store") as mock_agg:
                    mock_agg._client = None
                    from decision_api.main import app

                    app.state.http = AsyncMock()
                    app.dependency_overrides = {}
                    transport = httpx.ASGITransport(app=app)
                    async with httpx.AsyncClient(
                        transport=transport, base_url="http://testserver"
                    ) as c:
                        c.headers.update({"x-api-key": "test-key"})
                        yield c
                    app.dependency_overrides = {}


def test_kill_criteria_blocks_low_precision():
    gate = evaluate_kill_criteria(
        {"precision": 0.1, "recall": 0.9, "f1_score": 0.2},
        {"min_precision": 0.5, "min_recall": 0.3, "min_f1": 0.4},
        events_evaluated=500,
    )
    assert gate["promote_allowed"] is False
    assert gate["blockers"]


@pytest.mark.asyncio
async def test_promote_endpoint_returns_conflict_when_kill_fires(
    client, monkeypatch, tmp_path
):
    monkeypatch.setattr("decision_api.rule_api.settings.rules_path", str(tmp_path))
    monkeypatch.setattr(
        "decision_api.rule_api.evaluate_kill_criteria",
        lambda *a, **k: {"promote_allowed": False, "blockers": ["min_precision"]},
    )
    r = await client.post(
        "/v1/rules/vertical-packs/fintech/promote",
        json={
            "precision": 0.1,
            "recall": 0.9,
            "f1_score": 0.2,
            "events_evaluated": 500,
        },
    )
    assert r.status_code == 409
    detail = r.json()["detail"]
    assert "min_precision" in detail["blockers"]


@pytest.mark.asyncio
async def test_promote_endpoint_installs_when_kill_passes(
    client, monkeypatch, tmp_path
):
    monkeypatch.setattr("decision_api.rule_api.settings.rules_path", str(tmp_path))
    with patch("decision_api.rule_api.load_rules"):
        r = await client.post(
            "/v1/rules/vertical-packs/fintech/promote",
            json={
                "precision": 0.9,
                "recall": 0.9,
                "f1_score": 0.9,
                "false_positive_rate": 0.05,
                "events_evaluated": 500,
            },
        )
    assert r.status_code == 201
    data = r.json()
    assert data["vertical"] == "fintech"
    assert data["promoted"] is True
    assert data["rules"] >= 1


@pytest.mark.asyncio
async def test_promote_unknown_vertical_pack(client):
    r = await client.post(
        "/v1/rules/vertical-packs/unknown/promote",
        json={
            "precision": 0.9,
            "recall": 0.9,
            "f1_score": 0.9,
            "events_evaluated": 500,
        },
    )
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_install_endpoint_returns_conflict_when_kill_fires(
    client, monkeypatch, tmp_path
):
    monkeypatch.setattr("decision_api.rule_api.settings.rules_path", str(tmp_path))
    monkeypatch.setattr(
        "decision_api.rule_api.evaluate_kill_criteria",
        lambda *a, **k: {"promote_allowed": False, "blockers": ["min_precision"]},
    )
    r = await client.post(
        "/v1/rules/vertical-packs/fintech/install",
        json={
            "precision": 0.1,
            "recall": 0.9,
            "f1_score": 0.2,
            "events_evaluated": 500,
        },
    )
    assert r.status_code == 409
    detail = r.json()["detail"]
    assert "min_precision" in detail["blockers"]


@pytest.mark.asyncio
async def test_install_endpoint_installs_when_kill_passes(
    client, monkeypatch, tmp_path
):
    monkeypatch.setattr("decision_api.rule_api.settings.rules_path", str(tmp_path))
    with patch("decision_api.rule_api.load_rules"):
        r = await client.post(
            "/v1/rules/vertical-packs/fintech/install",
            json={
                "precision": 0.9,
                "recall": 0.9,
                "f1_score": 0.9,
                "false_positive_rate": 0.05,
                "events_evaluated": 500,
            },
        )
    assert r.status_code == 201
    data = r.json()
    assert data["vertical"] == "fintech"
    assert data["rules"] >= 1
    assert data["promote_gate"]["promote_allowed"] is True
