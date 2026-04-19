from __future__ import annotations

import os
import sys
from pathlib import Path

from fastapi.testclient import TestClient

os.environ.setdefault("ALLOW_INSECURE_NO_AUTH", "true")

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from counter_service.main import app


def test_health() -> None:
    with TestClient(app) as client:
        r = client.get("/v1/health")
    assert r.status_code == 200
    assert "status" in r.json()


def test_definition_lifecycle() -> None:
    with TestClient(app) as client:
        put = client.post(
            "/v1/definitions",
            json={
                "tenant_id": "t1",
                "definition_id": "velocity-default",
                "version": 1,
                "windows": ["5m", "1h", "24h"],
                "fields": ["amount", "ip_address", "device_id"],
            },
        )
        assert put.status_code == 201
        listed = client.get("/v1/definitions")
        assert listed.status_code == 200
        items = listed.json().get("items", [])
        assert any(i.get("definition_id") == "velocity-default" for i in items)
