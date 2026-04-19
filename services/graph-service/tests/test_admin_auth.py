from fastapi.testclient import TestClient

from graph_service.main import app


def test_admin_checkpoint_reload_requires_auth(monkeypatch):
    monkeypatch.delenv("API_KEYS", raising=False)
    monkeypatch.delenv("ALLOW_INSECURE_NO_AUTH", raising=False)
    with TestClient(app) as client:
        r = client.post("/v1/admin/checkpoint-profiles/reload")
    assert r.status_code == 503
