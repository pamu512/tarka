import os

from case_api.main import app
from fastapi.testclient import TestClient


def _api_headers() -> dict[str, str]:
    keys = [k.strip() for k in (os.environ.get("API_KEYS") or "").split(",") if k.strip()]
    assert keys
    return {"X-API-Key": keys[0]}


def test_case_views_are_persisted_and_update_by_name():
    with TestClient(app) as client:
        body = {
            "tenant_id": "demo",
            "name": "High Risk",
            "filters": {"priority": "high", "status": "open"},
        }
        r1 = client.post("/v1/case-views", json=body, headers=_api_headers())
        assert r1.status_code == 200, r1.text
        saved = r1.json()["view"]
        assert saved["name"] == "High Risk"
        assert saved["tenant_id"] == "demo"
        assert isinstance(saved.get("id"), str)

        r2 = client.get("/v1/case-views", params={"tenant_id": "demo"}, headers=_api_headers())
        assert r2.status_code == 200, r2.text
        items = r2.json()["items"]
        assert any(v["name"] == "High Risk" for v in items)

        r3 = client.post(
            "/v1/case-views",
            json={"tenant_id": "demo", "name": "High Risk", "filters": {"priority": "critical"}},
            headers=_api_headers(),
        )
        assert r3.status_code == 200, r3.text
        assert r3.json()["view"]["filters"]["priority"] == "critical"

        r4 = client.delete("/v1/case-views/High Risk", params={"tenant_id": "demo"}, headers=_api_headers())
        assert r4.status_code == 200, r4.text
        assert r4.json()["removed"] is True

        r5 = client.delete("/v1/case-views/High Risk", params={"tenant_id": "demo"}, headers=_api_headers())
        assert r5.status_code == 200, r5.text
        assert r5.json()["removed"] is False
