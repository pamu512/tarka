"""Unit tests for automated backup age classification (Prompt 173)."""

from __future__ import annotations

import importlib.util
from datetime import UTC, datetime, timedelta
from pathlib import Path

_MOD_PATH = (
    Path(__file__).resolve().parents[1]
    / "src"
    / "integration_ingress"
    / "automated_backup_indicators.py"
)
_spec = importlib.util.spec_from_file_location("automated_backup_indicators", _MOD_PATH)
assert _spec and _spec.loader
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)

_classify_backup_age = _mod._classify_backup_age
_parse_iso_ts = _mod._parse_iso_ts
_store_row = _mod._store_row


def test_parse_iso_ts_zulu() -> None:
    dt = _parse_iso_ts("2026-05-17T02:00:00Z")
    assert dt is not None
    assert dt.year == 2026


def test_classify_backup_age_buckets() -> None:
    assert _classify_backup_age(3600, ok_hours=26, warn_hours=50) == "ok"
    assert _classify_backup_age(30 * 3600, ok_hours=26, warn_hours=50) == "warn"
    assert _classify_backup_age(60 * 3600, ok_hours=26, warn_hours=50) == "stale"
    assert _classify_backup_age(None, ok_hours=26, warn_hours=50) == "unknown"


def test_store_row_missing_when_no_timestamp() -> None:
    row = _store_row(
        store_id="postgres",
        label="PostgreSQL",
        last_at=None,
        artifact_hint=None,
        size_bytes=None,
        source="test",
        ok_hours=26,
        warn_hours=50,
        schedule_hint="daily",
    )
    assert row["status"] == "missing"


def test_store_row_ok_when_recent() -> None:
    last = datetime.now(UTC) - timedelta(hours=2)
    row = _store_row(
        store_id="postgres",
        label="PostgreSQL",
        last_at=last,
        artifact_hint="postgres/nightly.sql.gz",
        size_bytes=1024,
        source="redis",
        ok_hours=26,
        warn_hours=50,
        schedule_hint="daily",
    )
    assert row["status"] == "ok"
    assert row["age_seconds"] is not None
