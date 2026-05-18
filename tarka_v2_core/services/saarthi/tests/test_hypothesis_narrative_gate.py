"""Gate (Prompt 195): Saarthi two-sentence hypothesis narrative from Scout bursts."""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from saarthi.hypothesis_narrative import (  # noqa: E402
    generate_hypothesis_narrative,
    generate_hypothesis_narrative_fallback,
    normalize_two_sentence_narrative,
    narrative_input_from_report,
)


def _sample_report(*, count: int = 50, hours: float = 2.0) -> dict:
    start = datetime(2026, 5, 18, 10, 0, tzinfo=UTC)
    end = datetime(2026, 5, 18, 12, 0, tzinfo=UTC)
    return {
        "report_id": "r-50",
        "strategy": "coordinated_burst",
        "fingerprint_kind": "canvas_hash",
        "fingerprint_value": "canvas_hash_999_xyz",
        "distinct_account_count": count,
        "window_start_utc": start.isoformat(),
        "window_end_utc": end.isoformat(),
        "account_ids": [f"acc_{i}" for i in range(min(count, 8))],
        "narrative": "technical",
        "confidence": 0.9,
    }


def test_gate_195_fallback_50_accounts_2_hours() -> None:
    report = _sample_report(count=50, hours=2.0)
    text = generate_hypothesis_narrative_fallback(report)
    assert normalize_two_sentence_narrative(text) == text
    assert "50 accounts" in text
    assert "2 hours" in text
    assert "botnet" in text.lower()


def test_generate_hypothesis_narrative_uses_fallback_without_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    scout = {"hypothesis_reports": [_sample_report()]}
    out = generate_hypothesis_narrative(scout, prefer_gemini=True)
    assert out["sentence_count"] == 2
    assert out["attribution_engine"] == "fallback"
    assert "50 accounts" in out["narrative"]


def test_narrative_input_window_hours() -> None:
    facts = narrative_input_from_report(_sample_report())
    assert facts["window_hours_elapsed"] == pytest.approx(2.0, abs=0.01)
    assert facts["distinct_account_count"] == 50


def test_normalize_rejects_three_sentences() -> None:
    assert (
        normalize_two_sentence_narrative("One. Two. Three.")
        is None
    )
