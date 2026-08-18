"""Observe-only pack canary on evaluate (issue #150 slice 1)."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from decision_api.config import settings


@pytest.fixture(autouse=True)
def _reset_canary(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setattr(settings, "pack_canary_percent", 0.0)
    monkeypatch.setattr(settings, "pack_canary_pack_id", "")
    monkeypatch.setattr(settings, "pack_canary_path", "")
    monkeypatch.setenv(
        "TARKA_ENFORCEMENT_JOURNAL_PATH", str(tmp_path / "enforcement.jsonl")
    )
    monkeypatch.setenv("API_KEYS", "test-key")
    monkeypatch.delenv("ALLOW_INSECURE_NO_AUTH", raising=False)
    monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    monkeypatch.setenv("FEATURE_SERVICE_URL", "")


@pytest.fixture
def candidate_pack_file(tmp_path):
    path = tmp_path / "candidate_canary.json"
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "name": "candidate_canary",
                "id": "candidate_canary",
                "rules": [
                    {
                        "id": "canary_always_deny",
                        "when": [{"field": "amount", "op": "gte", "value": 1}],
                        "tags": ["canary:candidate"],
                        "score_delta": 90,
                    }
                ],
                "tag_rules": [],
            }
        ),
        encoding="utf-8",
    )
    return path


@pytest.fixture
async def client():
    with (
        patch("decision_api.main.init_db", new_callable=AsyncMock),
        patch("decision_api.main.redis_tags") as mock_redis,
        patch("decision_api.main.load_rules"),
        patch("decision_api.main.agg_store") as mock_agg,
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
        from decision_api.main import app

        app.state.http = AsyncMock()
        app.dependency_overrides = {}
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://testserver"
        ) as c:
            c.headers.update({"x-api-key": "test-key"})
            c.tarka_app = app
            yield c
        app.dependency_overrides = {}


def _override_session_factory(mock_session):
    async def _override():
        yield mock_session

    return _override


def _session():
    mock_session = AsyncMock()
    mock_session.add = MagicMock()
    mock_session.commit = AsyncMock()
    return mock_session


async def _evaluate(client, mock_session, *, headers=None, payload=None):
    from decision_api.main import get_session

    body = payload or {
        "tenant_id": "t1",
        "event_type": "payment",
        "entity_id": "u1",
        "payload": {"amount": 100},
    }
    with (
        patch(
            "decision_api.main.evaluate_json_rules",
            return_value=([], [], 0.0, ["live.json"]),
        ),
        patch(
            "decision_api.main.evaluate_opa_or_raise",
            new_callable=AsyncMock,
            return_value=None,
        ),
        patch(
            "decision_api.main._fetch_ml_score_wrapped",
            new_callable=AsyncMock,
            return_value=(None, {}),
        ),
    ):
        client.tarka_app.dependency_overrides[get_session] = _override_session_factory(
            mock_session
        )
        r = await client.post(
            "/v1/decisions/evaluate", json=body, headers=headers or {}
        )
        client.tarka_app.dependency_overrides.pop(get_session, None)
    return r


@pytest.mark.asyncio
async def test_percent_zero_does_no_candidate_work(
    client, candidate_pack_file, monkeypatch
):
    monkeypatch.setattr(settings, "pack_canary_percent", 0.0)
    monkeypatch.setattr(settings, "pack_canary_path", str(candidate_pack_file))
    mock_session = _session()

    with patch("decision_api.json_rules.evaluate_adhoc_packs_json") as adhoc:
        r = await _evaluate(client, mock_session)
        adhoc.assert_not_called()

    assert r.status_code == 200
    data = r.json()
    assert data["decision"] == "allow"
    audit = mock_session.add.call_args[0][0]
    snap = audit.payload_snapshot or {}
    assert "pack_canary" not in snap


@pytest.mark.asyncio
async def test_percent_100_missing_pack_fail_closed(client, monkeypatch):
    monkeypatch.setattr(settings, "pack_canary_percent", 100.0)
    monkeypatch.setattr(settings, "pack_canary_pack_id", "does-not-exist")
    monkeypatch.setattr(settings, "pack_canary_path", "")
    mock_session = _session()

    r = await _evaluate(client, mock_session)
    assert r.status_code == 503
    detail = r.json()["detail"]
    assert detail["error"] == "pack_canary_candidate_missing"
    mock_session.add.assert_not_called()


@pytest.mark.asyncio
async def test_percent_100_fixture_records_candidate_live_verdict_unchanged(
    client, candidate_pack_file, monkeypatch
):
    monkeypatch.setattr(settings, "pack_canary_percent", 100.0)
    monkeypatch.setattr(settings, "pack_canary_path", str(candidate_pack_file))
    monkeypatch.setattr(settings, "json_rules_engine", "python")
    mock_session = _session()

    r = await _evaluate(client, mock_session)
    assert r.status_code == 200
    data = r.json()
    assert data["decision"] == "allow"
    assert "canary_always_deny" not in (data.get("rule_hits") or [])

    audit = mock_session.add.call_args[0][0]
    snap = audit.payload_snapshot or {}
    canary = snap.get("pack_canary") or {}
    assert canary.get("observe_only") is True
    assert canary.get("live_verdict_source") == "live_pack"
    assert canary.get("flagger") is False
    assert canary.get("candidate_decision") == "deny"
    assert "canary_always_deny" in (canary.get("candidate_rule_hits") or [])
    assert audit.decision == "allow"


@pytest.mark.asyncio
async def test_header_forces_candidate_when_percent_zero(
    client, candidate_pack_file, monkeypatch
):
    monkeypatch.setattr(settings, "pack_canary_percent", 0.0)
    monkeypatch.setattr(settings, "pack_canary_path", str(candidate_pack_file))
    monkeypatch.setattr(settings, "json_rules_engine", "python")
    mock_session = _session()

    r = await _evaluate(client, mock_session, headers={"x-tarka-pack-canary": "1"})
    assert r.status_code == 200
    assert r.json()["decision"] == "allow"
    audit = mock_session.add.call_args[0][0]
    canary = (audit.payload_snapshot or {}).get("pack_canary") or {}
    assert canary.get("forced") is True
    assert canary.get("candidate_decision") == "deny"
