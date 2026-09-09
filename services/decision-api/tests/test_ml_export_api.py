"""POST /v1/ml/export/pit-parquet orchestrates OLAP stream + case labels + Parquet."""

from __future__ import annotations

import asyncio
import json
import sys
import tempfile
from pathlib import Path

import httpx
import pytest
from httpx import ASGITransport, AsyncClient

_ANALYTICS_SRC = Path(__file__).resolve().parents[2] / "analytics" / "src"
_as = str(_ANALYTICS_SRC)
if _as not in sys.path:
    sys.path.insert(0, _as)

from analytics.engine import DuckDBEngine
from event_time import parse_event_time_to_unix


@pytest.mark.asyncio
async def test_pit_parquet_export_returns_file_uri(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
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
async def test_pit_parquet_export_503_when_case_api_unconfigured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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


@pytest.mark.asyncio
async def test_pit_parquet_export_job_polls_to_success(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from decision_api import ml_export_api
    from decision_api.config import settings
    from decision_api.main import app

    with ml_export_api._jobs_lock:
        ml_export_api._jobs.clear()

    monkeypatch.setenv("API_KEYS", "ml-export-job-key")
    monkeypatch.setenv("ALLOW_INSECURE_NO_AUTH", "false")
    monkeypatch.setattr(settings, "case_api_url", "http://case.test")
    monkeypatch.setattr(settings, "ml_export_local_dir", str(tmp_path))
    monkeypatch.setattr(settings, "ml_export_s3_bucket", "")

    p = Path(tempfile.gettempdir()) / "tarka-ml-export-job-test.duckdb"
    p.unlink(missing_ok=True)
    eng = DuckDBEngine(p)
    eng._conn.execute(
        """
        INSERT INTO fraud_decisions (
          tenant_id, entity_id, created_at, trace_id, decision, score, payload_json, rule_hits_json
        ) VALUES
        ('t1', 'e99', TIMESTAMP '2025-03-01 11:00:00', 'tr-job', 'review', 55.0, '{"amt": 42}', '[]')
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
                "/v1/ml/export/pit-parquet/jobs",
                headers={"x-api-key": "ml-export-job-key"},
                json={
                    "tenant_id": "t1",
                    "window_start": "2025-02-01T00:00:00Z",
                    "window_end": "2025-04-01T00:00:00Z",
                    "chunk_size": 500,
                    "payload_json_keys": ["amt"],
                    "dispute_outcome_allowlist": ["fraud_confirmed"],
                },
            )
        assert r.status_code == 200, r.text
        job_id = r.json()["job_id"]
        terminal: str | None = None
        last_body: dict | None = None
        async with AsyncClient(
            transport=transport, base_url="http://test"
        ) as poll_client:
            for _ in range(80):
                await asyncio.sleep(0.05)
                g = await poll_client.get(
                    f"/v1/ml/export/pit-parquet/jobs/{job_id}",
                    headers={"x-api-key": "ml-export-job-key"},
                )
                assert g.status_code == 200, g.text
                last_body = g.json()
                terminal = str(last_body.get("status") or "")
                if terminal in ("SUCCEEDED", "FAILED"):
                    break
        assert terminal == "SUCCEEDED", last_body
        assert last_body is not None
        assert last_body.get("progress_pct") == 100
        res = last_body.get("result") or {}
        assert res.get("rows_written") == 1
    finally:
        app.state.analytics_engine = prev
        eng.close()
        p.unlink(missing_ok=True)
        with ml_export_api._jobs_lock:
            ml_export_api._jobs.clear()


def test_holdout_split_for_ml_export_excludes_as_of_at_or_after_cutoff() -> None:
    from analytics.ml_export import apply_holdout_split
    from decision_api.ml_export_api import apply_holdout_split_for_ml_export

    t1 = "2026-01-01T10:00:00Z"
    t2 = "2026-01-01T10:00:00.500Z"
    rows = [
        {"as_of": "2026-01-01T09:00:00Z", "id": "early"},
        {"as_of": t1, "id": "at-cut"},
        {"as_of": t2, "id": "later"},
    ]
    train, hold = apply_holdout_split_for_ml_export(rows, cutoff=t1)
    via_helper = apply_holdout_split(rows, cutoff=t1)
    assert train == via_helper[0]
    assert hold == via_helper[1]
    assert [r["id"] for r in train] == ["early"]
    assert [r["id"] for r in hold] == ["at-cut", "later"]
    cut = parse_event_time_to_unix(t1)
    assert cut is not None
    for row in train:
        ts = parse_event_time_to_unix(row.get("as_of"))
        assert ts is not None and ts < cut


def test_run_point_in_time_ml_export_holdout_cutoff_drops_later_rows(
    tmp_path: Path,
) -> None:
    p = tmp_path / "holdout.duckdb"
    eng = DuckDBEngine(p)
    eng._conn.execute(
        """
        INSERT INTO fraud_decisions (
          tenant_id, entity_id, created_at, trace_id, decision, score, payload_json, rule_hits_json
        ) VALUES
        ('t1', 'e1', TIMESTAMP '2026-02-01 12:00:00', 'tr-early', 'review', 10.0, '{"amt": 1}', '[]'),
        ('t1', 'e2', TIMESTAMP '2026-02-03 12:00:00', 'tr-late', 'review', 20.0, '{"amt": 2}', '[]')
        """
    )
    out = tmp_path / "holdout.parquet"

    def _labels(trace_ids: list[str]) -> dict[str, dict[str, str]]:
        return {
            t: {
                "case_management_label": "fraud",
                "case_label_source": "dispute",
                "dispute_outcome": "fraud_confirmed",
            }
            for t in trace_ids
        }

    from analytics.ml_export import run_point_in_time_ml_export

    try:
        stats = run_point_in_time_ml_export(
            eng,
            table="fraud_decisions",
            tenant_id="t1",
            window_start_s="2026-01-01 00:00:00",
            window_end_s="2026-03-01 00:00:00",
            out_path=out,
            label_fetcher=_labels,
            chunk_size=10,
            clickhouse_max_execution_seconds=30,
            max_rows=10_000,
            holdout_cutoff="2026-02-02T00:00:00Z",
        )
        assert stats.rows_written == 1
    finally:
        eng.close()
