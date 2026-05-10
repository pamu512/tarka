"""FastAPI rule sidecar: ``POST /v1/evaluate``."""

from __future__ import annotations

import sys
from pathlib import Path

_SRC_RULE = Path(__file__).resolve().parents[1] / "src"
_SRC_INGESTOR = Path(__file__).resolve().parents[2] / "ingestor" / "src"
for _p in (_SRC_RULE, _SRC_INGESTOR):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from rule_engine.main import create_app  # noqa: E402
from starlette.testclient import TestClient  # noqa: E402


def test_v1_rules_reload_returns_count() -> None:
    app = create_app()
    with TestClient(app) as client:
        r = client.post("/v1/rules/reload")
    assert r.status_code == 200
    data = r.json()
    assert data.get("ok") is True
    assert isinstance(data.get("count"), int)


def test_health_returns_ok() -> None:
    app = create_app()
    with TestClient(app) as client:
        response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_v1_evaluate_returns_shadow_review_when_amount_exceeds_demo_threshold() -> None:
    app = create_app()
    body = {
        "entity_id": "77777777-7777-7777-7777-777777777777",
        "amount": 150.0,
        "timestamp": "2026-05-09T12:00:00+00:00",
        "metadata": {"channel": "wire"},
    }
    with TestClient(app) as client:
        response = client.post("/v1/evaluate", json=body)
    assert response.status_code == 200
    data = response.json()
    assert data["actions"] == ["SHADOW_REVIEW"]
    assert data["transaction_id"] == "77777777-7777-7777-7777-777777777777"


def test_v1_evaluate_returns_block_when_stress_block_lane_marker_present() -> None:
    app = create_app()
    body = {
        "entity_id": "66666666-6666-6666-6666-666666666666",
        "amount": 250.0,
        "timestamp": "2026-05-09T12:00:00+00:00",
        "metadata": {"lane": "STRESS_BLOCK_LANE"},
    }
    with TestClient(app) as client:
        response = client.post("/v1/evaluate", json=body)
    assert response.status_code == 200
    data = response.json()
    assert data["actions"] == ["BLOCK"]
    assert data["transaction_id"] == "66666666-6666-6666-6666-666666666666"


def test_v1_evaluate_returns_empty_actions_when_demo_rule_does_not_match() -> None:
    app = create_app()
    body = {
        "entity_id": "88888888-8888-8888-8888-888888888888",
        "amount": 50.0,
        "timestamp": "2026-05-09T12:00:00+00:00",
        "metadata": {},
    }
    with TestClient(app) as client:
        response = client.post("/v1/evaluate", json=body)
    assert response.status_code == 200
    assert response.json()["actions"] == []
