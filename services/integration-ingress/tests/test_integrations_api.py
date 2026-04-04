import os
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from urllib.parse import urlparse

import httpx
import pytest

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///")


@pytest.fixture
async def client():
    with patch("integration_ingress.main.init_db", new_callable=AsyncMock):
        with patch("integration_ingress.main._vault") as mock_vault:
            mock_vault.get_masked_config = AsyncMock(return_value={})
            mock_vault.get_config = AsyncMock(return_value={"api_key": "x"})
            mock_vault.set_config = AsyncMock()
            from integration_ingress.main import app, get_session

            session = AsyncMock()
            session.add = MagicMock()
            session.commit = AsyncMock()
            session.execute = AsyncMock()

            async def _override():
                yield session

            app.dependency_overrides[get_session] = _override
            app.state.http = AsyncMock()
            ok_resp = SimpleNamespace(status_code=200)
            app.state.http.get = AsyncMock(return_value=ok_resp)
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as c:
                c.test_session = session
                yield c
            app.dependency_overrides = {}


@pytest.mark.asyncio
async def test_catalog_contains_20(client):
    r = await client.get("/v1/integrations/catalog")
    assert r.status_code == 200
    assert r.json()["total_providers"] >= 20


@pytest.mark.asyncio
async def test_install_restricted_category_blocked_for_eu(client):
    r = await client.post(
        "/v1/integrations/install",
        json={"tenant_id": "t1", "provider_id": "jira", "config": {"region": "eu"}},
    )
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_test_connectivity_pass(client):
    session = client.test_session
    mock_conn = SimpleNamespace(last_connectivity_test=None, status="enabled")
    result = MagicMock()
    result.scalar_one_or_none.return_value = mock_conn
    session.execute.return_value = result
    r = await client.post(
        "/v1/integrations/test-connectivity",
        json={"tenant_id": "t1", "provider_id": "stripe_radar", "config": {"api_key": "k"}},
    )
    assert r.status_code == 200
    assert r.json()["status"] == "pass"
    assert "live_probe" in r.json()


@pytest.mark.asyncio
async def test_test_connectivity_pass_with_user_credentials(client):
    session = client.test_session
    mock_conn = SimpleNamespace(last_connectivity_test=None, status="enabled")
    result = MagicMock()
    result.scalar_one_or_none.return_value = mock_conn
    session.execute.return_value = result
    r = await client.post(
        "/v1/integrations/test-connectivity",
        json={"tenant_id": "t1", "provider_id": "jira", "config": {"username": "u", "password": "p"}},
    )
    assert r.status_code == 200
    assert r.json()["status"] == "pass"


@pytest.mark.asyncio
async def test_integration_request_pending_until_admin_approves(client):
    import integration_ingress.main as main_mod

    main_mod._integration_requests.clear()
    r = await client.post(
        "/v1/integrations/request",
        json={
            "tenant_id": "t1",
            "requested_name": "Acme KYB",
            "category": "kyc",
            "use_case": "Business verification for EU onboarding",
            "github_username": "dev1",
        },
    )
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "pending_approval"
    assert data.get("github_issue_url") in (None, "")
    assert "request" in data
    rid = data["request"]["id"]

    listed = await client.get("/v1/integrations/requests")
    assert listed.status_code == 200
    ids = [x["id"] for x in listed.json()["items"]]
    assert rid in ids

    appr = await client.post(f"/v1/integrations/requests/{rid}/approve", json={})
    assert appr.status_code == 200
    url = appr.json().get("github_issue_url", "")
    gh = urlparse(url)
    assert gh.hostname == "github.com"
    assert "/issues/new" in (gh.path or "")


@pytest.mark.asyncio
async def test_configure_idempotent_returns_snapshot(client):
    session = client.test_session
    op = SimpleNamespace(response_snapshot={"ok": True, "cached": True})
    result = MagicMock()
    result.scalar_one_or_none.return_value = op
    session.execute.return_value = result
    r = await client.post(
        "/v1/integrations/configure",
        headers={"Idempotency-Key": "abc123"},
        json={"tenant_id": "t1", "provider_id": "stripe_radar", "config": {"api_key": "x"}},
    )
    assert r.status_code == 200
    assert r.json().get("cached") is True
