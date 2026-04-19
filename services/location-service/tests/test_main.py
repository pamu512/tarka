import os
import sys
from pathlib import Path

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from location_service.main import app

os.environ.setdefault("ALLOW_INSECURE_NO_AUTH", "true")


def test_health():
    with TestClient(app) as client:
        r = client.get("/v1/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_resolve_and_evaluate_location():
    with TestClient(app) as client:
        rr = client.post(
            "/v1/resolve",
            json={
                "tenant_id": "t1",
                "device_geo": {"lat": 37.775, "lon": -122.419, "ts": 1_700_000_000, "source": "gps"},
                "ip_geo": {"lat": 37.78, "lon": -122.41, "ts": 1_700_000_000, "source": "ip"},
                "timezone": "America/Los_Angeles",
                "ip_timezone": "America/Los_Angeles",
            },
        )
        assert rr.status_code == 200
        resolved = rr.json()
        assert 0 <= resolved["confidence"] <= 1
        assert "resolved" in resolved

        er = client.post(
            "/v1/evaluate",
            json={
                "tenant_id": "t1",
                "entity_id": "e1",
                "current": {"lat": 37.775, "lon": -122.419, "ts": 1_700_000_000},
                "previous": {"lat": 40.7128, "lon": -74.0060, "ts": 1_699_990_000},
                "features": {"distinct_session_id_24h": 3},
            },
        )
        assert er.status_code == 200
        data = er.json()
        assert 0 <= data["location_confidence"] <= 1
        assert 0 <= data["copresence_risk"] <= 1
        assert 0 <= data["impossible_travel_risk"] <= 1
        assert "trace" in data


def test_trusted_places_round_trip():
    with TestClient(app) as client:
        put = client.put(
            "/v1/trusted-places/t1/e1",
            json={
                "places": [
                    {"lat": 37.775, "lon": -122.419, "radius_km": 2.0, "label": "hq"},
                ]
            },
        )
        assert put.status_code == 200
        get = client.get("/v1/trusted-places/t1/e1")
        assert get.status_code == 200
        payload = get.json()
        assert isinstance(payload.get("places"), list)
        assert payload["places"][0]["label"] == "hq"
