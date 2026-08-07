"""Sanctions screening journal tail + refresh stamp + schedule honesty."""

from __future__ import annotations

from pathlib import Path

from integration_ingress.sanctions import (
    SanctionsScreener,
    append_screening_journal,
    read_screening_journal,
    record_refresh_stamp,
    schedule_posture,
)


def test_read_screening_journal_newest_first(tmp_path: Path, monkeypatch):
    journal = tmp_path / "j.jsonl"
    monkeypatch.setenv("SANCTIONS_SCREENING_JOURNAL_PATH", str(journal))
    append_screening_journal({"schema_id": "tarka.sanctions_screening_journal/v1", "n": 1})
    append_screening_journal({"schema_id": "tarka.sanctions_screening_journal/v1", "n": 2})
    rows = read_screening_journal(limit=10)
    assert [r["n"] for r in rows] == [2, 1]


def test_refresh_stamp_and_schedule_gate_ops_ready(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("TARKA_SANCTIONS_REFRESH_SCHEDULE", raising=False)
    monkeypatch.setenv("SANCTIONS_REFRESH_STAMP_PATH", str(tmp_path / "stamp.json"))
    cache = tmp_path / "entities.ftm.json"
    cache.write_text("{}\n", encoding="utf-8")
    s = SanctionsScreener(cache_dir=tmp_path, cache_ttl=86_400)
    s._entities = [{"id": "1"}]
    s._loaded = True
    out = s.screening_ops_posture()
    assert out["ready_for_continuous_claim"] is True
    assert out["continuous_ops_ready"] is False
    assert "refresh_schedule_unset" in out["continuous_ops_blockers"]
    assert "no_refresh_stamp" in out["continuous_ops_blockers"]

    monkeypatch.setenv("TARKA_SANCTIONS_REFRESH_SCHEDULE", "0 */6 * * *")
    assert schedule_posture()["configured"] is True
    record_refresh_stamp(actor="admin", force_download=True)
    out2 = s.screening_ops_posture()
    assert out2["continuous_ops_ready"] is True
    assert out2["continuous_ops_blockers"] == []
    assert out2["continuous_bulk"]["refresh_count"] == 1
    assert out2["continuous_bulk"]["journal"].endswith("sanctions-screening-journal")
