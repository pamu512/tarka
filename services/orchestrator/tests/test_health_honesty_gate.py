"""S1 health honesty: the compose healthcheck must read process liveness, and
/health/full must fail loudly (503) when a probed dependency is unreachable.

Dive verdict S1-1: all live compose flavors probe :8790/health/full, which
returned 200 unconditionally — a dead decision/rule tier stayed "healthy"
(services/orchestrator/main.py returned the matrix regardless of statuses).
"""

from __future__ import annotations

import httpx
from fastapi.testclient import TestClient

import main  # orchestrator flat layout (conftest puts it on sys.path)


def _client(overrides: dict) -> TestClient:
    return TestClient(main.create_app(**overrides))


def test_health_liveness_route_exists_and_ok():
    """New bare /health: process liveness for compose/K8s probes."""
    client = _client({"rule_engine_url": "http://rule-engine:8000"})
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_health_full_is_503_when_probed_dependency_offline(monkeypatch):
    """Unreachable probed dep => 503; body keeps the per-component matrix."""

    def _refuse(self, *args, **kwargs):
        raise httpx.ConnectError("connection refused", request=None)

    monkeypatch.setattr(httpx.AsyncClient, "get", _refuse)
    client = _client({"rule_engine_url": "http://rule-engine:8000"})
    r = client.get("/health/full")
    assert r.status_code == 503
    statuses = {s["component"]: s["status"] for s in r.json()["services"]}
    assert statuses["rule_engine"] == "offline"
    assert statuses["orchestrator"] == "ok"


def test_health_full_stays_200_when_all_probes_ok(monkeypatch):
    class _OK:
        status_code = 200

    async def _ok(self, *args, **kwargs):
        return _OK()

    monkeypatch.setattr(httpx.AsyncClient, "get", _ok)
    client = _client({"rule_engine_url": "http://rule-engine:8000"})
    r = client.get("/health/full")
    assert r.status_code == 200
    statuses = {s["component"]: s["status"] for s in r.json()["services"]}
    assert statuses["rule_engine"] == "ok"
