"""Two-tenant evaluate isolation: API key A must not evaluate for tenant B."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

_KEY_A = "iso-eval-a"
_KEY_B = "iso-eval-b"
_TENANT_A = "tenant_alpha"
_TENANT_B = "tenant_beta"


@pytest.fixture
async def iso_client(monkeypatch, tmp_path):
    monkeypatch.setenv("API_KEYS", f"{_KEY_A},{_KEY_B}")
    monkeypatch.setenv("TENANT_BINDING_REQUIRED", "true")
    monkeypatch.setenv(
        "API_KEY_TENANT_MAP",
        json.dumps({_KEY_A: [_TENANT_A], _KEY_B: [_TENANT_B]}),
    )
    monkeypatch.delenv("ALLOW_INSECURE_NO_AUTH", raising=False)
    monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    monkeypatch.setenv("FEATURE_SERVICE_URL", "")
    monkeypatch.setenv(
        "TARKA_ENFORCEMENT_JOURNAL_PATH", str(tmp_path / "enforcement.jsonl")
    )

    import decision_api.main as main_mod

    with (
        patch.object(main_mod, "init_db", new_callable=AsyncMock),
        patch.object(main_mod, "redis_tags") as mock_redis,
        patch.object(main_mod, "load_rules"),
        patch.object(main_mod, "agg_store") as mock_agg,
    ):
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
        mock_agg._client = None
        app = main_mod.app
        app.state.http = AsyncMock()
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://testserver"
        ) as client:
            yield client


@pytest.mark.asyncio
async def test_evaluate_cross_tenant_forbidden(iso_client):
    payload = {
        "tenant_id": _TENANT_A,
        "entity_id": "buyer-iso",
        "amount": 10.0,
        "currency": "USD",
        "channel": "web",
    }
    cross = await iso_client.post(
        "/v1/decisions/evaluate",
        json=payload,
        headers={"X-API-Key": _KEY_B},
    )
    assert cross.status_code == 403, cross.text
    assert "outside caller scope" in cross.json()["detail"]

    # Own-tenant call must clear tenant binding (may still fail later for other
    # reasons in this mocked harness — only assert not 403).
    own = await iso_client.post(
        "/v1/decisions/evaluate",
        json={**payload, "tenant_id": _TENANT_B},
        headers={"X-API-Key": _KEY_B},
    )
    assert own.status_code != 403, own.text
