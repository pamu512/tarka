"""SR-16: sanctions match explain + JSONL journal mirror."""

import asyncio
from pathlib import Path

from integration_ingress.sanctions import (
    SanctionsScreener,
    append_screening_journal,
    screening_journal_path,
)


def test_screen_includes_matched_name_and_dampen(tmp_path: Path):
    s = SanctionsScreener(cache_dir=tmp_path, score_threshold=0.5)
    s._entities = [
        {
            "id": "Q1",
            "schema": "Person",
            "names": ["alice wonderland"],
            "countries": ["us"],
            "dobs": ["1990-01-01"],
            "topics": [],
            "caption": "Alice Wonderland",
        }
    ]
    s._loaded = True
    hits = asyncio.run(s.screen("Alice Wonderland", country="gb", dob="1991-01-01"))
    assert hits
    assert hits[0]["matched_name"] == "alice wonderland"
    assert "score_raw" in hits[0]
    assert hits[0]["score_threshold"] == 0.5
    assert "country_mismatch_x0.8" in hits[0]["score_dampens"]
    assert "dob_mismatch_x0.9" in hits[0]["score_dampens"]


def test_append_screening_journal(tmp_path: Path, monkeypatch):
    journal = tmp_path / "j.jsonl"
    monkeypatch.setenv("SANCTIONS_SCREENING_JOURNAL_PATH", str(journal))
    assert screening_journal_path() == journal
    append_screening_journal(
        {
            "schema_id": "tarka.sanctions_screening_journal/v1",
            "screening_log_id": "abc",
            "match_found": True,
        }
    )
    lines = journal.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    assert "abc" in lines[0]
