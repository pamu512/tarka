import os
from datetime import UTC, datetime
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
            async with httpx.AsyncClient(
                transport=transport,
                base_url="http://testserver",
                headers={"X-API-Key": (os.environ.get("API_KEYS") or "").split(",")[0].strip()},
            ) as c:
                c.test_session = session
                yield c
            app.dependency_overrides = {}


@pytest.mark.asyncio
async def test_catalog_contains_20(client):
    r = await client.get("/v1/integrations/catalog")
    assert r.status_code == 200
    data = r.json()
    assert data["total_providers"] >= 20
    assert data.get("connector_quality_version") == 1
    prov = next(p for p in data["providers"] if p["id"] == "jira")
    assert prov.get("swimlane_module")
    view_url = prov.get("github_project_view_url") or ""
    host = (urlparse(view_url).hostname or "").lower()
    assert host == "github.com" or host.endswith(".github.com")


@pytest.mark.asyncio
async def test_preflight_probes_returns_quality(client):
    r = await client.post(
        "/v1/integrations/preflight-probes", json={"provider_ids": ["stripe_radar"]}
    )
    assert r.status_code == 200
    data = r.json()
    assert data.get("connector_quality_version") == 1
    assert data["probed"] >= 1
    assert "average_connector_quality" in data
    row = data["results"][0]
    assert row["provider_id"] == "stripe_radar"
    assert "connector_quality" in row
    assert row["connector_quality"]["version"] == 1


@pytest.mark.asyncio
async def test_install_restricted_category_blocked_for_eu(client):
    r = await client.post(
        "/v1/integrations/install",
        json={"tenant_id": "t1", "provider_id": "jira", "config": {"region": "eu"}},
    )
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_install_rejects_byok_forbidden_platform_custody_keys(client):
    r = await client.post(
        "/v1/integrations/install",
        json={
            "tenant_id": "t1",
            "provider_id": "stripe_radar",
            "config": {"api_key": "k", "platform_api_key": "should-not-exist"},
        },
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
        json={
            "tenant_id": "t1",
            "provider_id": "jira",
            "config": {"username": "u", "password": "p"},
        },
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


@pytest.mark.asyncio
async def test_readiness_endpoint_returns_score(client):
    session = client.test_session
    result = MagicMock()
    result.all.return_value = [("kyc",), ("payments",)]
    session.execute.return_value = result
    r = await client.get("/v1/integrations/readiness", params={"tenant_id": "t1"})
    assert r.status_code == 200
    data = r.json()
    assert data["tenant_id"] == "t1"
    assert "readiness_score" in data
    assert "coverage" in data


@pytest.mark.asyncio
async def test_health_matrix_endpoint_shape(client):
    session = client.test_session
    row = SimpleNamespace(
        provider_id="stripe_radar",
        category="payments",
        status="enabled",
        last_connectivity_test={"status": "pass", "latency_ms": 12.3, "missing_fields": []},
    )
    result = MagicMock()
    result.scalars.return_value.all.return_value = [row]
    session.execute.return_value = result
    r = await client.get("/v1/integrations/health-matrix", params={"tenant_id": "t1"})
    assert r.status_code == 200
    data = r.json()
    assert data["tenant_id"] == "t1"
    assert data["rows"][0]["provider_id"] == "stripe_radar"
    assert data["rows"][0]["status"] == "pass"


@pytest.mark.asyncio
async def test_slo_endpoint(client):
    r = await client.get("/v1/slo")
    assert r.status_code == 200
    data = r.json()
    assert data["service"] == "integration-ingress"
    assert data.get("availability_target") == 99.9
    assert data.get("availability_target_pct") == 99.9
    assert "current" in data
    assert "http_requests_total_observed" in data["current"]


@pytest.mark.asyncio
async def test_scorecards_endpoint_shape(client):
    session = client.test_session
    row = SimpleNamespace(
        provider_id="stripe_radar",
        category="payments",
        status="enabled",
        last_connectivity_test={
            "status": "pass",
            "latency_ms": 18.4,
            "missing_fields": [],
            "live_probe": {"ok": True, "latency_ms": 11.0, "error": ""},
        },
        updated_at=datetime.now(UTC),
    )
    result = MagicMock()
    result.scalars.return_value.all.return_value = [row]
    session.execute.return_value = result

    r = await client.get("/v1/integrations/scorecards", params={"tenant_id": "t1"})
    assert r.status_code == 200
    data = r.json()
    assert data["tenant_id"] == "t1"
    assert "overall_score" in data
    assert len(data["providers"]) == 1
    p = data["providers"][0]
    assert p["provider_id"] == "stripe_radar"
    assert p["status"] in {"healthy", "degraded", "down", "unknown"}
    assert "connectivity_score" in p
    assert "config_completeness" in p
    assert "connector_quality" in p
    assert data.get("overall_connector_quality") is not None
    assert data["sla"]["trend_window_days"] == 7
    assert "remediation_hints" in data
