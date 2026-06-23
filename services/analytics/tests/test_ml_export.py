"""PIT ML export streams Parquet without materialising the full window in pandas."""

from __future__ import annotations

import json
from pathlib import Path

import pyarrow.parquet as pq
import pytest
from analytics.engine import DuckDBEngine
from analytics.ml_export import run_point_in_time_ml_export


def _labels_for(trace_ids: list[str]) -> dict[str, dict[str, str]]:
    return {
        t: {
            "case_management_label": "fraud" if t == "tr-a" else "not_fraud",
            "case_label_source": "dispute",
            "dispute_outcome": "fraud_confirmed" if t == "tr-a" else "false_positive",
        }
        for t in trace_ids
    }


@pytest.fixture
def duck_with_decisions(tmp_path: Path) -> DuckDBEngine:
    db = tmp_path / "ml.duckdb"
    eng = DuckDBEngine(db)
    eng.insert_batch(
        "fraud_decisions",
        [
            {
                "tenant_id": "t-export",
                "entity_id": "e1",
                "created_at": "2026-02-01 12:00:00",
                "trace_id": "tr-a",
                "decision": "review",
                "score": 62.5,
                "payload_json": json.dumps({"amount": 9000, "channel": "wire"}),
                "rule_hits_json": "[]",
            },
            {
                "tenant_id": "t-export",
                "entity_id": "e2",
                "created_at": "2026-02-02 08:30:00",
                "trace_id": "tr-b",
                "decision": "allow",
                "score": 12.0,
                "payload_json": json.dumps({"amount": 12}),
                "rule_hits_json": "[]",
            },
        ],
    )
    return eng


def test_run_point_in_time_ml_export_writes_parquet_in_batches(
    tmp_path: Path, duck_with_decisions: DuckDBEngine
) -> None:
    out = tmp_path / "out.parquet"

    stats = run_point_in_time_ml_export(
        duck_with_decisions,
        table="fraud_decisions",
        tenant_id="t-export",
        window_start_s="2026-02-01 00:00:00",
        window_end_s="2026-02-10 00:00:00",
        out_path=out,
        label_fetcher=_labels_for,
        chunk_size=1,
        clickhouse_max_execution_seconds=30,
        max_rows=10_000,
    )
    assert stats.rows_written == 2
    assert stats.chunks_processed == 2
    tbl = pq.read_table(out)
    assert tbl.num_rows == 2
    assert "feature_payload_json" in tbl.column_names
    assert "evaluation_time" in tbl.column_names
    payloads = tbl.column(tbl.column_names.index("feature_payload_json")).to_pylist()
    assert any("9000" in str(p) for p in payloads)


def test_run_point_in_time_ml_export_payload_json_key_subset(
    tmp_path: Path, duck_with_decisions: DuckDBEngine
) -> None:
    out = tmp_path / "subset.parquet"
    stats = run_point_in_time_ml_export(
        duck_with_decisions,
        table="fraud_decisions",
        tenant_id="t-export",
        window_start_s="2026-02-01 00:00:00",
        window_end_s="2026-02-10 00:00:00",
        out_path=out,
        label_fetcher=_labels_for,
        chunk_size=10,
        clickhouse_max_execution_seconds=30,
        max_rows=10_000,
        payload_json_keys=["amount"],
    )
    assert stats.rows_written == 2
    tbl = pq.read_table(out)
    payloads = tbl.column(tbl.column_names.index("feature_payload_json")).to_pylist()
    wire_row = next((p for p in payloads if "9000" in str(p)), None)
    assert wire_row is not None
    assert "channel" not in str(wire_row)


def test_run_point_in_time_ml_export_dispute_allowlist(
    tmp_path: Path, duck_with_decisions: DuckDBEngine
) -> None:
    out = tmp_path / "filtered.parquet"
    stats = run_point_in_time_ml_export(
        duck_with_decisions,
        table="fraud_decisions",
        tenant_id="t-export",
        window_start_s="2026-02-01 00:00:00",
        window_end_s="2026-02-10 00:00:00",
        out_path=out,
        label_fetcher=_labels_for,
        chunk_size=1,
        clickhouse_max_execution_seconds=30,
        max_rows=10_000,
        dispute_outcome_allowlist=frozenset({"fraud_confirmed"}),
    )
    assert stats.rows_written == 1
    tbl = pq.read_table(out)
    assert tbl.num_rows == 1
    tr = tbl.column(tbl.column_names.index("trace_id")).to_pylist()[0]
    assert tr == "tr-a"


def test_run_point_in_time_ml_export_progress_callback(
    tmp_path: Path, duck_with_decisions: DuckDBEngine
) -> None:
    out = tmp_path / "prog.parquet"
    snapshots: list[tuple[int, int]] = []

    def cb(stats) -> None:
        snapshots.append((stats.rows_written, stats.chunks_processed))

    run_point_in_time_ml_export(
        duck_with_decisions,
        table="fraud_decisions",
        tenant_id="t-export",
        window_start_s="2026-02-01 00:00:00",
        window_end_s="2026-02-10 00:00:00",
        out_path=out,
        label_fetcher=_labels_for,
        chunk_size=1,
        clickhouse_max_execution_seconds=30,
        max_rows=10_000,
        on_progress=cb,
    )
    assert snapshots
    assert snapshots[-1][0] == 2
