"""Tabular batch parse + store."""

from pathlib import Path

import pytest

from investigation_agent import batch_store
from investigation_agent.store_backend import StoreMisconfigured


def test_parse_csv():
    raw = b"a,b\n1,x\n2,y\n"
    cols, rows, fmt = batch_store.parse_tabular_file("t.csv", raw)
    assert fmt == "csv"
    assert cols == ["a", "b"]
    assert len(rows) == 2
    assert rows[0] == {"a": "1", "b": "x"}


def test_parse_json_array():
    raw = b'[{"id":1,"k":"a"},{"id":2,"k":"b"}]'
    cols, rows, fmt = batch_store.parse_tabular_file("t.json", raw)
    assert fmt == "json"
    assert "id" in cols and "k" in cols
    assert len(rows) == 2


def test_store_and_profile():
    cols = ["x"]
    rows = [{"x": "1"}, {"x": "2"}]
    bid = batch_store.store_batch("t1", "a1", "f.csv", cols, rows, "csv")
    rec = batch_store.get_batch(bid, "t1", "a1")
    assert rec is not None
    prof = batch_store.batch_profile(rec)
    assert prof["row_count"] == 2
    assert batch_store.get_batch(bid, "t1", "other") is None


def test_aggregate_value_counts():
    cols = ["status"]
    rows = [{"status": "ok"}, {"status": "ok"}, {"status": "fail"}]
    bid = batch_store.store_batch("t1", "a1", "f.csv", cols, rows, "csv")
    rec = batch_store.get_batch(bid, "t1", "a1")
    agg = batch_store.batch_aggregate_column(rec, "status", "value_counts")
    assert agg["distinct"] == 2
    assert agg["top_values"][0]["value"] == "ok"
    assert agg["top_values"][0]["count"] == 2


def test_aggregate_numeric():
    cols = ["amt"]
    rows = [{"amt": "10"}, {"amt": "20"}, {"amt": "bad"}]
    bid = batch_store.store_batch("t1", "a1", "f.csv", cols, rows, "csv")
    rec = batch_store.get_batch(bid, "t1", "a1")
    agg = batch_store.batch_aggregate_column(rec, "amt", "numeric_summary")
    assert agg["count"] == 2
    assert agg["min"] == 10.0
    assert agg["max"] == 20.0


def test_storage_mode_is_disk(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("BATCH_STORE_PATH", str(tmp_path / "batch-cache"))
    assert batch_store.storage_mode() == "disk"


def test_batch_persisted_under_configured_path(monkeypatch, tmp_path: Path):
    root = tmp_path / "batch-cache"
    monkeypatch.setenv("BATCH_STORE_PATH", str(root))
    cols = ["x"]
    rows = [{"x": "1"}, {"x": "2"}]
    bid = batch_store.store_batch("tenant-a", "analyst-a", "f.csv", cols, rows, "csv")
    json_files = list(root.glob("*.json"))
    assert json_files, "batch JSON should exist on disk"
    rec = batch_store.get_batch(bid, "tenant-a", "analyst-a")
    assert rec is not None
    assert rec["row_count"] == 2


def test_postgres_mode_without_url_fail_closed(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("INVESTIGATION_STORE", "postgres")
    monkeypatch.delenv("INVESTIGATION_DATABASE_URL", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("BATCH_STORE_PATH", str(tmp_path / "batch-cache"))
    batch_store.reset_connection_for_tests()
    try:
        with pytest.raises(StoreMisconfigured, match="DATABASE_URL"):
            batch_store.store_batch("t1", "a1", "f.csv", ["x"], [{"x": "1"}], "csv")
        root = tmp_path / "batch-cache"
        assert not root.exists() or not list(root.glob("*.json"))
    finally:
        batch_store.reset_connection_for_tests()


class _FakeCursor:
    def __init__(self, rows: list | None = None):
        self._rows = list(rows or [])

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return list(self._rows)


class _FakePostgres:
    """Minimal StoreConnection stand-in for batch_blobs INSERT/SELECT."""

    def __init__(self) -> None:
        self.blobs: dict[str, tuple] = {}

    def execute(self, sql: str, params=()):
        compact = " ".join(sql.split())
        if compact.startswith("INSERT INTO batch_blobs"):
            self.blobs[params[0]] = params
            return _FakeCursor()
        if compact.startswith("SELECT payload FROM batch_blobs"):
            rec = self.blobs.get(params[0])
            return _FakeCursor([(rec[4],)] if rec else [])
        if compact.startswith("DELETE FROM batch_blobs"):
            return _FakeCursor()
        if compact.startswith("SELECT job_id FROM batch_blobs"):
            return _FakeCursor([(job_id,) for job_id in self.blobs])
        return _FakeCursor()

    def commit(self) -> None:
        return None

    def close(self) -> None:
        return None


def test_postgres_mode_writes_and_reads_batch_blob(monkeypatch, tmp_path: Path):
    fake = _FakePostgres()
    monkeypatch.setenv("INVESTIGATION_STORE", "postgres")
    monkeypatch.setenv("INVESTIGATION_DATABASE_URL", "postgresql://fraud:pw@db.internal:5432/fraud")
    monkeypatch.setenv("BATCH_STORE_PATH", str(tmp_path / "should-not-write"))
    batch_store.reset_connection_for_tests()
    monkeypatch.setattr(batch_store, "_get_pg_conn", lambda: fake)
    try:
        assert batch_store.storage_mode() == "postgres"
        bid = batch_store.store_batch(
            "ten-pg", "analyst-pg", "jobs.csv", ["x"], [{"x": "blob"}], "csv"
        )
        assert bid in fake.blobs
        payload = fake.blobs[bid][4]
        assert isinstance(payload, (bytes, bytearray))
        rec = batch_store.get_batch(bid, "ten-pg", "analyst-pg")
        assert rec is not None
        assert rec["rows"][0]["x"] == "blob"
        assert rec["row_count"] == 1
        assert batch_store.get_batch(bid, "ten-pg", "other") is None
        disk = tmp_path / "should-not-write"
        assert not disk.exists() or not list(disk.glob("*.json"))
    finally:
        batch_store.reset_connection_for_tests()
