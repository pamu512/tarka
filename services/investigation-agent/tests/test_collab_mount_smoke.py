"""Smoke: collaboration-chat-bridge remains mounted at /collab after the split."""

from fastapi.testclient import TestClient

from investigation_agent.main import app


def test_collab_health_mounted():
    r = TestClient(app).get("/collab/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["service"] == "collaboration-chat-bridge"
    assert body["investigation_agent_configured"] is True
