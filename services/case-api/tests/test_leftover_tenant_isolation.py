"""Two-tenant leftover isolation: API key A must not see tenant B leftovers."""

from __future__ import annotations

import asyncio
import json
import os
from unittest.mock import AsyncMock, patch

import pytest
from case_api.workflow import WorkflowContext
from fastapi.testclient import TestClient
from sqlalchemy import delete

_KEY_A = "iso-key-a"
_KEY_B = "iso-key-b"
_TENANT_A = "tenant_alpha"
_TENANT_B = "tenant_beta"


@pytest.fixture
def iso_client(monkeypatch):
    monkeypatch.setenv("API_KEYS", f"{_KEY_A},{_KEY_B}")
    monkeypatch.setenv("TENANT_BINDING_REQUIRED", "true")
    monkeypatch.setenv(
        "API_KEY_TENANT_MAP",
        json.dumps({_KEY_A: [_TENANT_A], _KEY_B: [_TENANT_B]}),
    )
    monkeypatch.delenv("ALLOW_INSECURE_NO_AUTH", raising=False)

    from case_api.db import SessionLocal
    from case_api.main import app
    from case_api.models import Case, LeftoverPromoteAck

    async def _wipe():
        async with SessionLocal() as session:
            await session.execute(delete(LeftoverPromoteAck))
            await session.execute(delete(Case))
            await session.commit()

    with patch("case_api.main.evaluate_workflows", new_callable=AsyncMock) as ev:
        ev.return_value = WorkflowContext("case_created", {})
        with TestClient(app) as client:
            asyncio.run(_wipe())
            yield client


def _hdr(key: str) -> dict[str, str]:
    return {"X-API-Key": key}


def test_leftover_list_cross_tenant_forbidden(iso_client):
    created = iso_client.post(
        "/v1/cases",
        json={
            "tenant_id": _TENANT_A,
            "title": "Auto: deny payment e-iso",
            "entity_id": "e-iso-a",
            "trace_id": "tr-iso-a",
            "labels": ["origin:evaluate"],
            "last_outcome": "deny",
        },
        headers=_hdr(_KEY_A),
    )
    assert created.status_code == 201, created.text

    own = iso_client.get(
        "/v1/leftovers",
        params={"tenant_id": _TENANT_A},
        headers=_hdr(_KEY_A),
    )
    assert own.status_code == 200, own.text
    assert "e-iso-a" in {r["entity_id"] for r in own.json()["leftovers"]}

    cross = iso_client.get(
        "/v1/leftovers",
        params={"tenant_id": _TENANT_A},
        headers=_hdr(_KEY_B),
    )
    assert cross.status_code == 403, cross.text
    assert "outside caller scope" in cross.json()["detail"]

    empty = iso_client.get(
        "/v1/leftovers",
        params={"tenant_id": _TENANT_B},
        headers=_hdr(_KEY_B),
    )
    assert empty.status_code == 200, empty.text
    assert empty.json()["leftovers"] == []
