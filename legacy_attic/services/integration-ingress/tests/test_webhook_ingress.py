"""Gate: KYC webhook normalization must fail closed (422 + DLQ) or commit normalized inbox rows."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

_LEGACY_SRC = Path(__file__).resolve().parents[1] / "src"
_SHARED = Path(__file__).resolve().parents[2] / "shared"
for _p in (_LEGACY_SRC, _SHARED):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///")
os.environ.setdefault("API_KEYS", "test-integration-key")
os.environ.setdefault("SERVICE_API_KEY_ROLE", "admin")

from integration_ingress.adapters import ADAPTERS  # noqa: E402
from integration_ingress.webhook_ingress import WEBHOOK_NORMALIZATION_FAILED_DETAIL  # noqa: E402


async def _failing_adapter(_t: str, _s: str, _raw: dict[str, Any] | None) -> dict[str, Any]:
    raise KeyError("required_field")


@pytest.fixture
async def webhook_client():
    with patch("integration_ingress.main.init_db", new_callable=AsyncMock):
        with patch("integration_ingress.main._vault") as mock_vault:
            mock_vault.get_masked_config = AsyncMock(return_value={})
            from integration_ingress.main import app, get_session

            session = AsyncMock()
            session.add = MagicMock()
            session.commit = AsyncMock()

            async def _override():
                yield session

            app.dependency_overrides[get_session] = _override
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(
                transport=transport,
                base_url="http://testserver",
                headers={"X-API-Key": os.environ["API_KEYS"]},
            ) as client:
                client.test_session = session  # type: ignore[attr-defined]
                yield client
            app.dependency_overrides = {}


@pytest.mark.asyncio
async def test_malformed_webhook_returns_422(webhook_client: httpx.AsyncClient) -> None:
    session = webhook_client.test_session  # type: ignore[attr-defined]
    with patch.dict(ADAPTERS, {"broken": _failing_adapter}, clear=False):
        r = await webhook_client.post(
            "/v1/webhooks/kyc/broken",
            json={"tenant": "t1", "incomplete": True},
        )
    assert r.status_code == 422
    assert r.json()["detail"] == WEBHOOK_NORMALIZATION_FAILED_DETAIL
    session.add.assert_not_called()
    session.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_valid_webhook_dispatches_downstream(webhook_client: httpx.AsyncClient) -> None:
    session = webhook_client.test_session  # type: ignore[attr-defined]
    payload = {"subject_id": "sub-1", "document_type": "passport"}
    r = await webhook_client.post("/v1/webhooks/kyc/mock", json=payload)
    assert r.status_code == 200
    body = r.json()
    assert body["accepted"] is True
    assert body["normalized"] is True
    assert body["provider"] == "mock"

    session.add.assert_called_once()
    record = session.add.call_args[0][0]
    assert record.status == "normalized"
    assert record.provider == "mock"
    assert record.normalized is not None
    assert record.normalized.get("adapter") == "mock"
    session.commit.assert_awaited_once()
