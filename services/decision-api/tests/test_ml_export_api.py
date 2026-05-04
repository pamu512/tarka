"""POST /v1/ml/export/pit-parquet orchestrates OLAP stream + case labels + Parquet."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import httpx
import pytest
from httpx import ASGITransport, AsyncClient

from analytics.engine import DuckDBEngine


@pytest.mark.asyncio
async def test_pit_parquet_export_returns_file_uri(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from decision_api.config import settings
    from decision_api.main import app

    monkeypatch.setenv("API_KEYS", "ml-export-test-key")
    monkeypatch.setenv("ALLOW_INSECURE_NO_AUTH", "false")
    monkeypatch.setattr(settings, "case_api_url", "http://case.test")
    monkeypatch.setattr(settings, "ml_export_local_dir", str(tmp_path))
    monkeypatch.setattr(settings, "ml_export_s3_bucket", "")

    p = Path(tempfile.gettempdir()) / "tarka-ml-export-api-test.duckdb"
    p.unlink(missing_ok=True)
    eng = DuckDBEngine(p)
    eng._conn.execute(
        """
        INSERT INTO fraud_decisions (
          tenant_id, entity_id, created_at, trace_id, decision, score, payload_json, rule_hits_json
        ) VALUES
        ('t1', 'e99', TIMESTAMP '2025-03-01 11:00:00', 'tr-ml-exp', 'review', 55.0, '{"amt": 42}', '[]')
        """
    )

    prev = getattr(app.state, "analytics_engine", None)
    app.state.analytics_engine = eng

    _RealClient = httpx.Client

    def _mock_client(**kw: object) -> httpx.Client:
        timeout = kw.get("timeout", 120.0)

        def handler(request: httpx.Request) -> httpx.Response:
            b = json.loads(request.content.decode() or "{}")
            tids = b.get("trace_ids") or []
            labs = {
                t: {
                    "case_management_label": "fraud",
                    "case_label_source": "dispute",
                    "dispute_outcome": "fraud_confirmed",
                    "label_resolved_at": "2025-03-15T00:00:00+00:00",
                }
                for t in tids
            }
            return httpx.Response(200, json={"labels": labs})

        return _RealClient(transport=httpx.MockTransport(handler), timeout=timeout)  # type: ignore[arg-type]

    monkeypatch.setattr("decision_api.ml_export_api.httpx.Client", _mock_client)

    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            r = await client.post(
                "/v1/ml/export/pit-parquet",
                headers={"x-api-key": "ml-export-test-key"},
                json={
                    "tenant_id": "t1",
                    "window_start": "2025-02-01T00:00:00Z",
                    "window_end": "2025-04-01T00:00:00Z",
                    "chunk_size": 500,
                },
            )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["rows_written"] == 1
        assert body["chunks_processed"] == 1
        assert body["artifact_uri"].startswith("file://")
        assert body["presigned_get_url"] is None
        assert Path(body["local_path"]).is_file()
    finally:
        app.state.analytics_engine = prev
        eng.close()
        p.unlink(missing_ok=True)


@pytest.mark.asyncio
async def test_pit_parquet_export_503_when_case_api_unconfigured(monkeypatch: pytest.MonkeyPatch) -> None:
    from decision_api.config import settings
    from decision_api.main import app

    monkeypatch.setenv("API_KEYS", "ml-export-test-key2")
    monkeypatch.setenv("ALLOW_INSECURE_NO_AUTH", "false")
    monkeypatch.setattr(settings, "case_api_url", "")

    p = Path(tempfile.gettempdir()) / "tarka-ml-export-503.duckdb"
    p.unlink(missing_ok=True)
    eng = DuckDBEngine(p)
    prev = getattr(app.state, "analytics_engine", None)
    app.state.analytics_engine = eng
    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            r = await client.post(
                "/v1/ml/export/pit-parquet",
                headers={"x-api-key": "ml-export-test-key2"},
                json={
                    "tenant_id": "t1",
                    "window_start": "2025-01-01T00:00:00Z",
                    "window_end": "2026-01-01T00:00:00Z",
                },
            )
        assert r.status_code == 503
        assert "CASE_API_URL" in r.json()["detail"]
    finally:
        app.state.analytics_engine = prev
        eng.close()
        p.unlink(missing_ok=True)
