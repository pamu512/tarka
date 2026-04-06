"""HTTP batch ingest."""

from fastapi.testclient import TestClient
from investigation_agent.main import app


def test_batch_ingest_csv_multipart():
    with TestClient(app) as client:
        files = {"file": ("sample.csv", b"entity_id,amount\ne1,100\ne2,200\n", "text/csv")}
        data = {"tenant_id": "demo", "analyst_id": "analyst-1"}
        r = client.post("/v1/batch/ingest", data=data, files=files)
    assert r.status_code == 200, r.text
    j = r.json()
    assert "batch_id" in j
    assert j["row_count"] == 2
    assert "entity_id" in j["columns"]


def test_governance_endpoint():
    with TestClient(app) as client:
        r = client.get("/v1/governance")
    assert r.status_code == 200
    j = r.json()
    assert j["profile"] in ("us", "eu_uk", "global")
    assert "references" in j and isinstance(j["references"], list)


def test_chat_accepts_batch_id():
    payload = {
        "tenant_id": "demo",
        "analyst_id": "analyst-1",
        "batch_id": "00000000-0000-4000-8000-000000000001",
        "messages": [{"role": "user", "content": "hello"}],
    }
    with TestClient(app) as client:
        r = client.post("/v1/chat", json=payload)
    assert r.status_code == 200
    body = r.json()
    assert "reply" in body
