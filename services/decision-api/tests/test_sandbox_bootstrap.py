"""Sandbox bootstrap route (mock Postgres)."""

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest


@asynccontextmanager
async def _acquire_cm(conn):
    yield conn


@asynccontextmanager
async def _tx_cm():
    yield


class _FakeConn:
    def __init__(self) -> None:
        self.executes: list[tuple[str, tuple]] = []
        self._approval_checks = 0

    def transaction(self):
        return _tx_cm()

    async def execute(self, query: str, *args: object) -> str:
        self.executes.append((query, args))
        return "OK"

    async def fetchval(self, query: str, *args: object):
        if "rule_approvals" in query:
            self._approval_checks += 1
            if self._approval_checks == 1:
                return None
            return 1
        return 1


class _FakePool:
    def __init__(self, conn: _FakeConn) -> None:
        self._conn = conn

    def acquire(self):
        return _acquire_cm(self._conn)


@pytest.fixture
def sb_client():
    pytest.importorskip("asyncpg")
    import decision_api.main as _main_mod  # noqa: F401

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

            with patch("decision_api.main.load_rules"):
                with patch("decision_api.main.agg_store") as mock_agg:
                    mock_agg._client = None
                    from decision_api.deps import get_pg_pool
                    from decision_api.main import app

                    app.state.http = AsyncMock()
                    app.state.pg_pool = None
                    app.dependency_overrides = {}

                    fake_conn = _FakeConn()

                    def _pool(_: object) -> _FakePool:
                        return _FakePool(fake_conn)

                    app.dependency_overrides[get_pg_pool] = _pool

                    transport = httpx.ASGITransport(app=app)
                    with httpx.Client(
                        transport=transport, base_url="http://testserver"
                    ) as c:
                        c.headers.update({"x-api-key": "test-key"})
                        c.tarka_fake_conn = fake_conn
                        c.tarka_app = app
                        yield c
                    app.dependency_overrides = {}


def test_sandbox_bootstrap_idempotent(monkeypatch, sb_client):
    captured: list[object] = []

    def _capture(pack):
        captured.append(pack)

    monkeypatch.setattr(
        "decision_api.sandbox_bootstrap.set_plg_sandbox_runtime_pack", _capture
    )

    r1 = sb_client.post("/v1/sandbox/bootstrap")
    assert r1.status_code == 200, r1.text
    body1 = r1.json()
    assert body1["merged_rule_count"] == 5
    assert body1["rule_approval_inserted"] is True
    assert len(captured) == 1
    assert len(captured[0]["rules"]) == 5

    r2 = sb_client.post("/v1/sandbox/bootstrap")
    assert r2.status_code == 200
    body2 = r2.json()
    assert body2["rule_approval_inserted"] is False
    assert len(captured) == 2

    # Two upsert rounds: templates + bundle + optional approval lookup each time
    assert len(sb_client.tarka_fake_conn.executes) >= 6
