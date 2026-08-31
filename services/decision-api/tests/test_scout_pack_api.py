"""Tests for POST /v1/rules/scout-pack — scout suggestion → observe pack."""

from __future__ import annotations

import json
import os
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")


@pytest.fixture(autouse=True)
def _patch_env(monkeypatch):
    monkeypatch.setenv("API_KEYS", "test-key")
    monkeypatch.delenv("ALLOW_INSECURE_NO_AUTH", raising=False)
    monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    monkeypatch.setenv("FEATURE_SERVICE_URL", "")


@pytest.fixture
async def client(tmp_path, monkeypatch):
    monkeypatch.setenv("RULES_PATH", str(tmp_path))
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
                    from decision_api.config import settings

                    orig = settings.rules_path
                    settings.rules_path = str(tmp_path)
                    try:
                        from decision_api.main import app

                        async def _allow_leftover(tid, pack):
                            ids = [
                                str(r.get("id") or "").strip()
                                for r in (pack.get("rules") or [])
                                if isinstance(r, dict)
                                and str(r.get("id") or "").strip()
                            ]
                            return {
                                "publish_allowed": True,
                                "reason": None,
                                "keep_rule_ids": ids,
                                "stamp_underpowered": False,
                                "should_kill": False,
                                "_helpfulness": {},
                            }

                        monkeypatch.setattr(
                            "decision_api.rule_api._scout_leftover_verdict",
                            _allow_leftover,
                        )
                        app.state.http = AsyncMock()
                        app.dependency_overrides = {}
                        transport = httpx.ASGITransport(app=app)
                        async with httpx.AsyncClient(
                            transport=transport, base_url="http://testserver"
                        ) as c:
                            c.headers.update({"x-api-key": "test-key"})
                            c._rules_dir = tmp_path
                            yield c
                        app.dependency_overrides = {}
                    finally:
                        settings.rules_path = orig


def _scout_pack_body() -> dict:
    return {
        "name": "Scout: canvas_hash abc123",
        "mode": "shadow",
        "rules": [
            {
                "id": "scout_canvas_hash_abc123",
                "when": [{"op": "eq", "field": "canvas_hash", "value": "abc123"}],
                "score_delta": 25.0,
                "metadata": {
                    "is_shadow": True,
                    "source": "scout_coordinated_burst",
                    "fingerprint_kind": "canvas_hash",
                },
            }
        ],
        "authored_by": "scout_coordinated_burst",
        "is_ai_authored": True,
        "scout_report_id": "rpt-001",
        "tenant_id": "t1",
    }


class TestScoutPackEndpoint:
    @pytest.mark.asyncio
    async def test_create_scout_pack(self, client):
        r = await client.post("/v1/rules/scout-pack", json=_scout_pack_body())
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["mode"] == "shadow"
        assert body["file"].startswith("scout_")
        assert body["file"].endswith(".json")
        pack = body["pack"]
        assert pack["mode"] == "shadow"
        assert pack["is_ai_authored"] is True
        assert pack["authored_by"] == "scout_coordinated_burst"
        assert len(pack["rules"]) == 1

    @pytest.mark.asyncio
    async def test_scout_pack_persisted_to_disk(self, client):
        r = await client.post("/v1/rules/scout-pack", json=_scout_pack_body())
        assert r.status_code == 201
        filename = r.json()["file"]
        fpath = client._rules_dir / filename
        assert fpath.is_file()
        loaded = json.loads(fpath.read_text(encoding="utf-8"))
        assert loaded["mode"] == "shadow"
        assert loaded["is_ai_authored"] is True

    @pytest.mark.asyncio
    async def test_scout_pack_appears_in_list(self, client):
        r = await client.post("/v1/rules/scout-pack", json=_scout_pack_body())
        assert r.status_code == 201
        r2 = await client.get("/v1/rules")
        assert r2.status_code == 200
        packs = r2.json()["packs"]
        scout_packs = [p for p in packs if p.get("is_ai_authored")]
        assert len(scout_packs) >= 1
        assert scout_packs[0]["mode"] == "shadow"

    @pytest.mark.asyncio
    async def test_scout_pack_rejects_active_mode(self, client):
        body = _scout_pack_body()
        body["mode"] = "active"
        r = await client.post("/v1/rules/scout-pack", json=body)
        assert r.status_code == 400

    @pytest.mark.asyncio
    async def test_scout_pack_change_log(self, client):
        r = await client.post("/v1/rules/scout-pack", json=_scout_pack_body())
        assert r.status_code == 201
        r2 = await client.get("/v1/rules/change-log")
        assert r2.status_code == 200
        items = r2.json()["items"]
        assert any(i["action"] == "create_scout_pack" for i in items)
        entry = next(i for i in items if i["action"] == "create_scout_pack")
        assert entry["detail"]["is_ai_authored"] is True
        assert entry["detail"]["authored_by"] == "scout_coordinated_burst"

    @pytest.mark.asyncio
    async def test_scout_pack_excluded_from_active_evaluation(self, client):
        """Shadow-mode packs must NOT be evaluated in production (exclude_shadow=True)."""
        r = await client.post("/v1/rules/scout-pack", json=_scout_pack_body())
        assert r.status_code == 201
        pack = r.json()["pack"]
        from decision_api.pack_evaluator import _iter_eligible_packs

        eligible = _iter_eligible_packs([pack], exclude_shadow=True)
        assert len(eligible) == 0
        eligible_shadow = _iter_eligible_packs([pack], exclude_shadow=False)
        assert len(eligible_shadow) == 1

    @pytest.mark.asyncio
    async def test_reject_missing_is_ai_authored(self, client):
        body = _scout_pack_body()
        body["is_ai_authored"] = False
        r = await client.post("/v1/rules/scout-pack", json=body)
        assert r.status_code == 422
        detail = r.json()["detail"]
        assert detail["contract"] == "ai_authored_pack"
        assert any("is_ai_authored" in e for e in detail["validation_errors"])

    @pytest.mark.asyncio
    async def test_reject_score_delta_out_of_bounds(self, client):
        body = _scout_pack_body()
        body["rules"][0]["score_delta"] = 50.0
        r = await client.post("/v1/rules/scout-pack", json=body)
        assert r.status_code == 422
        assert any("score_delta" in e for e in r.json()["detail"]["validation_errors"])

    @pytest.mark.asyncio
    async def test_reject_unknown_field(self, client):
        body = _scout_pack_body()
        body["rules"][0]["when"] = [{"op": "eq", "field": "evil_field", "value": "x"}]
        r = await client.post("/v1/rules/scout-pack", json=body)
        assert r.status_code == 422
        assert any(
            "unknown field" in e for e in r.json()["detail"]["validation_errors"]
        )

    @pytest.mark.asyncio
    async def test_reject_unknown_op(self, client):
        body = _scout_pack_body()
        body["rules"][0]["when"] = [
            {"op": "execute_sql", "field": "canvas_hash", "value": "x"}
        ]
        r = await client.post("/v1/rules/scout-pack", json=body)
        assert r.status_code == 422
        assert any(
            "disallowed op" in e for e in r.json()["detail"]["validation_errors"]
        )

    @pytest.mark.asyncio
    async def test_reject_empty_rules(self, client):
        body = _scout_pack_body()
        body["rules"] = []
        r = await client.post("/v1/rules/scout-pack", json=body)
        assert r.status_code == 422
