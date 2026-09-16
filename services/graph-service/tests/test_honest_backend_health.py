"""Honest health: /v1/health must probe the configured graph backend.

The route used to return ``status: ok`` with a backend *label* only — a down
Postgres/AGE still reported healthy. The health probe must actually touch the
backend driver and surface reachability, degrading the top-level status for the
core engine (AGE) while pads report their own state without failing the plane.
"""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

_SRC = Path(__file__).resolve().parents[1]
for _p in (_SRC / "src",):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

os.environ.setdefault("ALLOW_INSECURE_NO_AUTH", "true")
os.environ.pop("API_KEYS", None)


class _FakeConn:
    async def fetchval(self, _sql: str) -> int:
        return 1


class _FakePool:
    # asyncpg.Pool.acquire() is itself the async context manager.
    def acquire(self):
        class _Ctx:
            async def __aenter__(self):
                return _FakeConn()

            async def __aexit__(self, *_a):
                return False

        return _Ctx()


async def _fake_get_pool():
    return _FakePool()


class TestHonestBackendHealth(unittest.IsolatedAsyncioTestCase):
    def test_health_reports_ok_when_backend_reachable(self) -> None:
        from fastapi.testclient import TestClient

        import graph_service.main as m

        with patch.object(m, "_backend_reachable", return_value=True), TestClient(m.app) as client:
            r = client.get("/v1/health")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["status"], "ok")
        self.assertTrue(body["graph_backend"]["reachable"])

    def test_health_degrades_when_core_backend_down(self) -> None:
        from fastapi.testclient import TestClient

        import graph_service.main as m

        with patch.object(m, "_backend_reachable", return_value=False), TestClient(m.app) as client:
            r = client.get("/v1/health")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["status"], "degraded")
        self.assertFalse(body["graph_backend"]["reachable"])

    async def test_reachability_probe_uses_pool(self) -> None:
        import graph_service.main as m
        from graph_service import age_client

        with patch.object(age_client, "get_pool", _fake_get_pool):
            ok = await m._backend_reachable("age")
        self.assertTrue(ok)


if __name__ == "__main__":
    unittest.main()
