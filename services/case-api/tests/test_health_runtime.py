"""Smoke: GET /v1/health exposes runtime DB bootstrap hints."""

import os
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient


def test_health_runtime_fields_present():
    with patch("case_api.main.init_db", new_callable=AsyncMock):
        from case_api.main import app

        with (
            patch("case_api.main.active_database_backend", return_value="postgresql"),
            patch("case_api.main.public_database_url", return_value="postgresql+asyncpg://fraud:***@db:5432/fraud_cases"),
            patch("case_api.main.using_local_fallback", return_value=False),
            patch("case_api.main.fallback_reason", return_value=None),
            patch("case_api.main.bootstrap_mode", return_value="alembic_head"),
        ):
            keys = [k.strip() for k in (os.environ.get("API_KEYS") or "").split(",") if k.strip()]
            headers = {"X-API-Key": keys[0]} if keys else {}
            with TestClient(app) as client:
                r = client.get("/v1/health", headers=headers)
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "ok"
    assert data["database_backend"] == "postgresql"
    assert data["database_url"].endswith("@db:5432/fraud_cases")
    assert data["database_fallback_active"] is False
    assert data["database_fallback_reason"] is None
    assert data["database_bootstrap_mode"] == "alembic_head"
