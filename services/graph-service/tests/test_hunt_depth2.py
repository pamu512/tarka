"""R2: Hunt depth-2, opt-in and contract-gated.

Default posture is unchanged (hunt_depth_max=1, cap + degrade token). Depth-2
walks only when the operator enables HUNT_DEPTH_2_ENABLED, and only via an
explicit fixed 2-edge pattern (no AGE 1.6 variable-length paths). Honesty
fields keep their semantics: depth_applied is the real walk.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from graph_service import hunt_depth


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("ALLOW_INSECURE_NO_AUTH", "true")
    from graph_service.main import app as _app

    with TestClient(_app) as c:
        yield c


def test_walk_depth_two_requires_flag(monkeypatch):
    monkeypatch.delenv("HUNT_DEPTH_2_ENABLED", raising=False)
    import importlib

    import graph_service.hunt_depth as hd

    importlib.reload(hd)
    assert hd.hunt_walk_depth(2) == 1  # cap holds when flag unset
    assert hd.HUNT_DEPTH_MAX == 1  # schema constant unchanged


def test_walk_depth_two_when_enabled(monkeypatch):
    monkeypatch.setenv("HUNT_DEPTH_2_ENABLED", "true")
    import importlib

    import graph_service.hunt_depth as hd

    importlib.reload(hd)
    assert hd.hunt_walk_depth(2) == 2
    assert hd.hunt_walk_depth(5) == 2  # depth-2 is the ceiling, not unlimited
    assert hd.hunt_walk_depth(1) == 1
    monkeypatch.delenv("HUNT_DEPTH_2_ENABLED", raising=False)
    importlib.reload(hd)


def test_default_off_keeps_existing_cap_behavior(client, monkeypatch):
    from unittest.mock import AsyncMock

    mock = AsyncMock(return_value={"nodes": [], "edges": []})
    monkeypatch.setattr("graph_service.main.query_subgraph", mock)
    r = client.get("/v1/subgraph", params={"tenant_id": "t", "entity_id": "u", "depth": 2})
    body = r.json()
    assert body["depth_applied"] == 1
    assert body["degrade_reason"] == "hunt:depth_capped"


def test_depth_two_route_walks_two_when_enabled(client, monkeypatch):
    from unittest.mock import AsyncMock

    monkeypatch.setenv("HUNT_DEPTH_2_ENABLED", "true")
    mock = AsyncMock(return_value={"nodes": [], "edges": []})
    monkeypatch.setattr("graph_service.main.query_subgraph", mock)
    r = client.get("/v1/subgraph", params={"tenant_id": "t", "entity_id": "u", "depth": 2})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["depth_applied"] == 2
    assert body["degrade_reason"] is None
    assert mock.await_args.args == ("t", "u", 2)
    monkeypatch.delenv("HUNT_DEPTH_2_ENABLED", raising=False)


def test_age_query_subgraph_2hop_is_explicit_pattern():
    """Depth-2 must be an explicit 2-edge MATCH (AGE 1.6 has no [*1..n])."""
    from pathlib import Path

    import graph_service.age_client as ac

    src = Path(ac.__file__).read_text(encoding="utf-8")
    assert "]-[e2]-(" in src or "e2" in src, "second-hop pattern missing"
