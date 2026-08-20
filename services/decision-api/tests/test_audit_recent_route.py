"""Route ordering: GET /v1/audit/recent must not be captured by /v1/audit/{trace_id}."""

from fastapi import FastAPI, Query
from fastapi.testclient import TestClient
from uuid import UUID


def test_recent_is_not_captured_as_uuid():
    """Regression: before the fix, ``/v1/audit/recent`` was parsed as trace_id=recent → 422."""
    app = FastAPI()

    @app.get("/v1/audit/recent")
    async def audit_recent(tenant_id: str = Query("demo")):
        return {"route": "recent", "tenant_id": tenant_id}

    @app.get("/v1/audit/{trace_id}")
    async def audit_by_trace(trace_id: UUID):
        return {"route": "trace", "trace_id": str(trace_id)}

    client = TestClient(app)

    r = client.get("/v1/audit/recent", params={"tenant_id": "demo"})
    assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text}"
    assert r.json()["route"] == "recent"

    r2 = client.get(
        "/v1/audit/00000000-0000-0000-0000-000000000001",
        params={"tenant_id": "demo"},
    )
    assert r2.status_code == 200
    assert r2.json()["route"] == "trace"


def test_recent_rejects_non_uuid_as_trace_id():
    """A non-UUID, non-'recent' path segment should still be rejected by the {trace_id} route."""
    app = FastAPI()

    @app.get("/v1/audit/recent")
    async def audit_recent():
        return {"route": "recent"}

    @app.get("/v1/audit/{trace_id}")
    async def audit_by_trace(trace_id: UUID):
        return {"route": "trace"}

    client = TestClient(app)
    r = client.get("/v1/audit/not-a-uuid")
    assert r.status_code == 422
