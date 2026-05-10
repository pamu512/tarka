import os

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    from chitragupta import plugin_sdk as ps

    ps._REGISTRY.clear()
    os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"
    from chitragupta.main import app

    with TestClient(app) as c:
        yield c


def test_run_dual_emitters_deterministic(client: TestClient):
    body = {
        "tenant_id": "t1",
        "plugin_id": "scorecard.json",
        "input": {"rows": [{"metric": "precision", "v": "0.9"}], "tenant_id": "t1"},
        "emitters": ["json", "csv"],
    }
    r = client.post("/v1/runs", json=body)
    assert r.status_code == 201, r.text
    data = r.json()
    assert data["status"] == "completed"
    assert "json" in data["artifacts"] and "csv" in data["artifacts"]
    r2 = client.post("/v1/runs", json=body)
    assert r2.json()["input_hash"] == data["input_hash"]
    g = client.get(f"/v1/runs/{data['run_id']}")
    assert g.status_code == 200
    assert g.json()["plugin_id"] == "scorecard.json"


def test_register_rejects_contract_major_mismatch(client: TestClient):
    r = client.post(
        "/v1/plugins/register",
        json={
            "plugin_id": "bad.major",
            "contract_version": "99.0.0",
            "capabilities": {},
            "emitter_targets_supported": ["json"],
        },
    )
    assert r.status_code == 400


def test_emitter_retry_run(client: TestClient):
    body = {
        "tenant_id": "t1",
        "plugin_id": "scorecard.json",
        "input": {"k": "v"},
        "emitters": ["json"],
        "simulate_emitter_failures": 1,
    }
    r = client.post("/v1/runs", json=body)
    assert r.status_code == 201, r.text
    logs = r.json()["emitter_logs"]
    assert logs[0]["emitter"] == "json"
    assert len(logs[0]["attempts"]) >= 2
