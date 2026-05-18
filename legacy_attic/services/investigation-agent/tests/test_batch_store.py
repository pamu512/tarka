"""Tabular batch parse + store."""

from pathlib import Path

from investigation_agent import batch_store


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
