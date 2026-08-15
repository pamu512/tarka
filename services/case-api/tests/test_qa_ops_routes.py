"""QA ops routes must be wired on the app, not just present as source strings."""

from __future__ import annotations

import os
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from case_api.db import get_session


class _EmptyResult:
    def all(self):
        return []


class _FakeSession:
    async def execute(self, *_a, **_k):
        return _EmptyResult()

    async def get(self, *_a, **_k):
        return None

    async def commit(self):
        return None


async def _override_session():
    yield _FakeSession()


def test_qa_ops_routes_respond():
    with patch("case_api.main.init_db", new_callable=AsyncMock):
        from case_api.main import app

        app.dependency_overrides[get_session] = _override_session
        keys = [k.strip() for k in (os.environ.get("API_KEYS") or "").split(",") if k.strip()]
        headers = {"X-API-Key": keys[0]} if keys else {}
        try:
            with TestClient(app) as client:
                sample = client.get(
                    "/v1/cases/ops/qa-sample",
                    params={"tenant_id": "demo"},
                    headers=headers,
                )
                metrics = client.get(
                    "/v1/cases/ops/qa-metrics",
                    params={"tenant_id": "demo"},
                    headers=headers,
                )
                review = client.post(
                    "/v1/cases/ops/qa-review",
                    json={},
                    headers=headers,
                )
        finally:
            app.dependency_overrides.pop(get_session, None)

    assert sample.status_code == 200
    assert sample.json()["tenant_id"] == "demo"
    assert metrics.status_code == 200
    assert "reviewed" in metrics.json()
    assert review.status_code == 400
