"""GET /v1/compliance/residency/audit and CSV export."""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient
from integration_ingress.compliance_residency import init_residency_matrix_store
from integration_ingress.config import settings
from integration_ingress.db import Base, get_session
from integration_ingress.main import app
from integration_ingress.models import ComplianceResidencyAudit
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


@pytest.fixture
async def audit_client(tmp_path, monkeypatch: pytest.MonkeyPatch):
    """SQLite-backed ``get_session`` override so tests do not require Postgres."""
    monkeypatch.setattr(settings, "residency_matrix_json_path", str(tmp_path / "matrix-audit.json"))
    init_residency_matrix_store(json_path=str(tmp_path / "matrix-audit.json"))

    db_path = tmp_path / "residency_audit_test.db"
    url = f"sqlite+aiosqlite:///{db_path}"
    eng = create_async_engine(url)
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(eng, class_=AsyncSession, expire_on_commit=False)

    async def _override_session() -> AsyncIterator[AsyncSession]:
        async with factory() as session:
            yield session

    app.dependency_overrides[get_session] = _override_session
    transport = ASGITransport(app=app)
    key = (os.environ.get("API_KEYS") or "").split(",")[0].strip()
    headers = {"X-API-Key": key}
    async with AsyncClient(transport=transport, base_url="http://test", headers=headers) as client:
        yield client

    app.dependency_overrides.pop(get_session, None)
    await eng.dispose()
    init_residency_matrix_store(json_path="")


@pytest.mark.asyncio
async def test_residency_audit_list_and_csv_export(audit_client: AsyncClient, tmp_path) -> None:
    rid = uuid.uuid4()
    eng = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/residency_audit_test.db")
    async with AsyncSession(eng, expire_on_commit=False) as session:
        session.add(
            ComplianceResidencyAudit(
                id=rid,
                tenant_id="audit-tenant-1",
                component="osint",
                vendor_key="shodan",
                tenant_region="EU",
                vendor_region="US",
                outcome="compliance_block",
                detail="EU cannot call US vendor",
                request_url_preview="https://example.test/x",
            )
        )
        await session.commit()

    try:
        r = await audit_client.get(
            "/v1/compliance/residency/audit",
            params={"page": 1, "page_size": 10, "tenant_id": "audit-tenant-1"},
        )
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["total"] >= 1
        assert any(it.get("id") == str(rid) for it in data["items"])

        c = await audit_client.get(
            "/v1/compliance/residency/audit/export.csv",
            params={"tenant_id": "audit-tenant-1"},
        )
        assert c.status_code == 200, c.text
        assert "text/csv" in (c.headers.get("content-type") or "")
        body = c.text
        assert "id,tenant_id,component" in body
        assert str(rid) in body
        assert "shodan" in body
    finally:
        async with AsyncSession(eng, expire_on_commit=False) as session:
            await session.execute(
                delete(ComplianceResidencyAudit).where(ComplianceResidencyAudit.id == rid)
            )
            await session.commit()
        await eng.dispose()
