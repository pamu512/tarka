from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from investigation_agent import feedback_store, review_store
from investigation_agent.main import app


@pytest.fixture(autouse=True)
def _isolated_stores(tmp_path, monkeypatch):
    monkeypatch.setenv("INVESTIGATION_DATA_DIR", str(tmp_path))
    feedback_store.reset_connection_for_tests()
    review_store.reset_connection_for_tests()
    yield
    feedback_store.reset_connection_for_tests()
    review_store.reset_connection_for_tests()


def test_plugin_session_and_bootstrap(monkeypatch):
    import investigation_agent.main as m

    monkeypatch.setattr(m.settings, "copilot_plugin_shared_secret", "plugin-secret", raising=False)
    monkeypatch.setattr(m.settings, "copilot_maker_checker_required", True, raising=False)
    with TestClient(app) as c:
        issued = c.post(
            "/v1/plugin/session",
            json={"tenant_id": "demo", "analyst_id": "analyst-1", "case_id": "case-1"},
            headers={"X-Request-Id": "req-plugin-1"},
        )
        assert issued.status_code == 200, issued.text
        body = issued.json()
        assert body["ok"] is True
        assert body["context"]["case_id"] == "case-1"
        assert body["correlation_id"] == "req-plugin-1"
        assert issued.headers.get("x-correlation-id") == "req-plugin-1"
        assert isinstance(body.get("token"), str) and body["token"]

        boot = c.post(
            "/v1/plugin/bootstrap",
            json={"token": body["token"]},
            headers={"X-Request-Id": "req-plugin-2"},
        )
        assert boot.status_code == 200, boot.text
        boot_body = boot.json()
        assert boot_body["ok"] is True
        assert boot_body["correlation_id"] == "req-plugin-2"
        assert boot.headers.get("x-correlation-id") == "req-plugin-2"
        assert boot_body["session"]["tenant_id"] == "demo"
        assert boot_body["session"]["analyst_id"] == "analyst-1"
        assert boot_body["governance"]["assurance_defaults"]["maker_checker_required"] is True


def test_plugin_bootstrap_invalid_token_has_correlation_header(monkeypatch):
    import investigation_agent.main as m

    monkeypatch.setattr(m.settings, "copilot_plugin_shared_secret", "plugin-secret", raising=False)
    with TestClient(app) as c:
        r = c.post(
            "/v1/plugin/bootstrap",
            json={"token": "bad-token"},
            headers={"X-Request-Id": "req-bad-1"},
        )
    assert r.status_code == 401
    assert r.headers.get("x-correlation-id") == "req-bad-1"


def test_turn_review_enforces_maker_checker(monkeypatch):
    import investigation_agent.main as m

    monkeypatch.setattr(m.settings, "copilot_maker_checker_required", True, raising=False)
    feedback_store.record_turn(
        turn_id="turn-maker-1",
        tenant_id="demo",
        analyst_id="analyst-maker",
        case_id="case-1",
        playbook_id=None,
        prompt_version="3.2.0",
        reply_preview="preview",
        tool_count=0,
    )
    with TestClient(app) as c:
        rejected = c.post(
            "/v1/review/turn",
            json={
                "turn_id": "turn-maker-1",
                "tenant_id": "demo",
                "analyst_id": "analyst-maker",
                "status": "approved",
            },
        )
        assert rejected.status_code == 400
        assert "maker-checker" in rejected.json().get("detail", "")

        accepted = c.post(
            "/v1/review/turn",
            json={
                "turn_id": "turn-maker-1",
                "tenant_id": "demo",
                "analyst_id": "analyst-maker",
                "reviewer_id": "analyst-checker",
                "status": "approved",
            },
        )
        assert accepted.status_code == 200, accepted.text
        body = accepted.json()
        assert body["maker_checker"]["required"] is True
        assert body["maker_checker"]["turn_author_id"] == "analyst-maker"
        assert body["maker_checker"]["reviewer_id"] == "analyst-checker"


def test_review_metrics_endpoint(monkeypatch):
    import investigation_agent.main as m

    monkeypatch.setattr(m.settings, "copilot_maker_checker_required", False, raising=False)
    review_store.save_review(
        turn_id="turn-a",
        tenant_id="demo",
        analyst_id="checker-1",
        status="approved",
        note=None,
    )
    review_store.save_review(
        turn_id="turn-b",
        tenant_id="demo",
        analyst_id="checker-2",
        status="rejected",
        note="needs edits",
    )
    with TestClient(app) as c:
        r = c.get("/v1/review/metrics", params={"tenant_id": "demo", "days": 30})
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["tenant_id"] == "demo"
    assert data["total_reviews"] == 2
    assert data["approved"] == 1
    assert data["rejected"] == 1
    assert data["unique_reviewers"] == 2
