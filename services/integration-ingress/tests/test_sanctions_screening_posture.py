"""OpenSanctions continuous screening ops posture."""

from __future__ import annotations

from pathlib import Path

from integration_ingress.sanctions import SanctionsScreener


def test_screening_ops_posture_not_loaded(tmp_path: Path):
    s = SanctionsScreener(cache_dir=tmp_path)
    out = s.screening_ops_posture()
    assert out["schema_id"] == "tarka.sanctions_screening_ops_posture/v1"
    assert out["continuous_bulk"]["status"] == "not_loaded"
    assert out["ready_for_continuous_claim"] is False
    assert out["realtime_match_api"]["plugin"] == "opensanctions"
    assert "Motiva" in out["vs_marble"]


def test_screening_ops_posture_ready(tmp_path: Path, monkeypatch):
    cache = tmp_path / "entities.ftm.json"
    cache.write_text("{}\n", encoding="utf-8")
    journal = tmp_path / "sanctions_screening_journal.jsonl"
    journal.write_text('{"match_found":true}\n', encoding="utf-8")
    monkeypatch.setenv("SANCTIONS_SCREENING_JOURNAL_PATH", str(journal))
    s = SanctionsScreener(cache_dir=tmp_path, cache_ttl=86_400)
    s._entities = [{"id": "1"}]
    s._loaded = True
    out = s.screening_ops_posture()
    assert out["continuous_bulk"]["status"] == "ready"
    assert out["continuous_bulk"]["entities_loaded"] == 1
    assert out["continuous_bulk"]["screening_journal_lines"] == 1
    assert out["continuous_bulk"]["refresh"].endswith("sanctions-screening-refresh")
    assert out["ready_for_continuous_claim"] is True
