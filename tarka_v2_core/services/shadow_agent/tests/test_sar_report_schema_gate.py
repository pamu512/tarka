"""Gate (Prompt 131): ``SARReportSchema`` validates coerced model-shaped payloads."""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError
from shadow_agent.schemas import SARReportSchema


def test_sar_report_schema_accepts_llm_shaped_dict_and_json_roundtrip() -> None:
    """Simulate loose LLM output (numeric strings), force through Pydantic, assert invariants."""
    raw = {
        "primary_suspect": "Entity shell_acct_7 / linked user usr_gate_131",
        "laundering_volume": "48250.25",
        "narrative": (
            "Layered deposits below CTR thresholds followed by outbound wires to high-risk "
            "correspondent; pattern consistent with structuring per internal typology T-131."
        ),
        "confidence": "0.73",
    }
    report = SARReportSchema.model_validate(raw)
    assert report.primary_suspect.startswith("Entity shell_acct")
    assert report.laundering_volume == pytest.approx(48250.25)
    assert "structuring" in report.narrative.lower()
    assert report.confidence == pytest.approx(0.73)

    dumped = report.model_dump()
    again = SARReportSchema.model_validate(dumped)
    assert again == report

    text = json.dumps(dumped)
    parsed = json.loads(text)
    SARReportSchema.model_validate(parsed)


def test_sar_report_schema_rejects_invalid_confidence() -> None:
    with pytest.raises(ValidationError):
        SARReportSchema.model_validate(
            {
                "primary_suspect": "x",
                "laundering_volume": 1.0,
                "narrative": "y",
                "confidence": 1.5,
            },
        )
