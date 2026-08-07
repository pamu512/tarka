"""Integration: PATCH dispute outcome triggers decision-api y_label merge (mocked httpx)."""

import os
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient


def _headers() -> dict[str, str]:
    keys = [k.strip() for k in (os.environ.get("API_KEYS") or "").split(",") if k.strip()]
    assert keys
    return {"X-API-Key": keys[0]}


@pytest.fixture
def dispute_merge_client():
    import case_api.main  # noqa: F401

    merge_mock = AsyncMock(return_value=None)
    with (
        patch("case_api.main.evaluate_workflows", new_callable=AsyncMock),
        patch("case_api.dispute_api._send_ml_feedback", new_callable=AsyncMock),
        patch("case_api.dispute_api._merge_dispute_y_label", merge_mock) as merge_patch,
    ):
        from case_api.main import app

        with TestClient(app) as client:
            yield client, merge_patch


def test_patch_dispute_outcome_triggers_y_label_merge(dispute_merge_client) -> None:
    client, merge_mock = dispute_merge_client
    h = _headers()
    create = {
        "tenant_id": "tenant-ymerge",
        "entity_id": "ent-ymerge",
        "trace_id": "trace-ymerge-1",
        "dispute_type": "chargeback",
        "amount": 99.0,
    }
    r = client.post("/v1/disputes", json=create, headers=h)
    assert r.status_code == 201, r.text
    did = r.json()["id"]

    merge_mock.reset_mock()
    r2 = client.patch(f"/v1/disputes/{did}", json={"outcome": "false_positive"}, headers=h)
    assert r2.status_code == 200, r2.text
    merge_mock.assert_awaited_once()


@pytest.mark.asyncio
async def test_merge_dispute_y_label_posts_to_decision_api(monkeypatch) -> None:
    from case_api.dispute_api import _merge_dispute_y_label
    from types import SimpleNamespace

    posted: list[tuple[str, dict]] = []

    class _Resp:
        status_code = 200

        def json(self):
            return {"ok": True}

    class _Http:
        async def post(self, url, json=None, headers=None, timeout=None):
            posted.append((url, json or {}))
            return _Resp()

    monkeypatch.setattr("case_api.dispute_api.settings.decision_api_url", "http://decision.test")
    monkeypatch.setattr("case_api.dispute_api.settings.decision_api_key", "test-key")

    dispute = SimpleNamespace(
        id="d1",
        tenant_id="acme",
        trace_id="trace-merge-1",
        outcome="fraud_confirmed",
    )
    await _merge_dispute_y_label(_Http(), dispute)

    assert len(posted) == 1
    url, body = posted[0]
    assert url == "http://decision.test/v1/calibration/y-labels/merge"
    assert body["tenant_id"] == "acme"
    assert body["labels"][0]["trace_id"] == "trace-merge-1"
    assert body["labels"][0]["y_label"] == "1"
    assert body["labels"][0]["source"] == "dispute"


@pytest.mark.asyncio
async def test_merge_dispute_y_label_skips_inconclusive(monkeypatch) -> None:
    from case_api.dispute_api import _merge_dispute_y_label
    from types import SimpleNamespace

    called = False

    class _Http:
        async def post(self, *args, **kwargs):
            nonlocal called
            called = True
            raise AssertionError("should not POST for inconclusive")

    monkeypatch.setattr("case_api.dispute_api.settings.decision_api_url", "http://decision.test")
    dispute = SimpleNamespace(
        id="d2",
        tenant_id="acme",
        trace_id="trace-merge-2",
        outcome="inconclusive",
    )
    await _merge_dispute_y_label(_Http(), dispute)
    assert not called
