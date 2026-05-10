"""Smoke: GET /v1/admin/db/migration-status exposes expected/current revisions."""

import os
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient


def test_admin_migration_status_endpoint():
    expected_payload = {
        "state": "drift",
        "expected_heads": ["20260421_004_case_views_table"],
        "current_versions": ["20260402_001_case_schema"],
        "current_versions_error": None,
        "database_backend": "postgresql",
        "database_url": "postgresql+asyncpg://fraud:***@db:5432/fraud_cases",
        "database_fallback_active": False,
        "database_fallback_reason": None,
        "database_bootstrap_mode": "alembic_head",
        "runbook_hint": "Run `alembic upgrade head` against case-api DB and restart service when state=drift.",
        "note": "Current DB revision(s) differ from expected Alembic head(s).",
    }
    with patch("case_api.main.init_db", new_callable=AsyncMock):
        from case_api.main import app

        with patch(
            "case_api.main.migration_status", new_callable=AsyncMock, return_value=expected_payload
        ):
            keys = [k.strip() for k in (os.environ.get("API_KEYS") or "").split(",") if k.strip()]
            headers = {"X-API-Key": keys[0]} if keys else {}
            with TestClient(app) as client:
                r = client.get("/v1/admin/db/migration-status", headers=headers)
    assert r.status_code == 200
    data = r.json()
    assert data["state"] == "drift"
    assert data["expected_heads"] == expected_payload["expected_heads"]
    assert data["current_versions"] == expected_payload["current_versions"]
