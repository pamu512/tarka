"""POST /v1/calibration/y-labels/merge persists trace labels."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from decision_api.calibration_api import router as calibration_router
from decision_api.y_label_store import load_y_labels


@pytest.fixture
async def merge_client(tmp_path, monkeypatch):
    monkeypatch.setenv("ALLOW_INSECURE_NO_AUTH", "true")
    monkeypatch.setenv("CALIBRATION_DATA_DIR", str(tmp_path))

    from auth_rbac import AuthUser

    app = FastAPI()

    @app.middleware("http")
    async def _inject_auth(request, call_next):
        request.state.auth_user = AuthUser(
            "test-analyst", ["analyst", "admin"], "test", tenant_ids={"*"}
        )
        return await call_next(request)

    app.include_router(calibration_router)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


@pytest.mark.asyncio
async def test_y_labels_merge_endpoint(merge_client):
    r = await merge_client.post(
        "/v1/calibration/y-labels/merge",
        json={
            "tenant_id": "acme-merge",
            "labels": [
                {"trace_id": "t-fraud", "y_label": "FRAUD", "source": "dispute"},
                {"trace_id": "t-legit", "y_label": "0", "source": "dispute"},
                {"trace_id": "t-skip", "y_label": "maybe", "source": "dispute"},
            ],
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert body["merged"] == 2
    assert body["skipped"] == 1
    assert body["source_breakdown"]["dispute"] == 2

    stored = load_y_labels("acme-merge")
    assert stored["by_trace"]["t-fraud"] == "1"
    assert stored["by_trace"]["t-legit"] == "0"
    assert "t-skip" not in stored["by_trace"]
