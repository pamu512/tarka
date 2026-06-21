"""Gate (Prompt 133): SAR PDF from Shadow JSON includes the Regulatory Summary section."""

from __future__ import annotations

import io
import sys
from pathlib import Path

import pytest
from pypdf import PdfReader

_SRC_SAARTHI = Path(__file__).resolve().parents[1] / "src"
if str(_SRC_SAARTHI) not in sys.path:
    sys.path.insert(0, str(_SRC_SAARTHI))

from saarthi.pdf_generator import (  # noqa: E402
    REGULATORY_SUMMARY_HEADING,
    sar_shadow_json_to_formal_pdf_bytes,
)


def test_sar_pdf_contains_regulatory_summary_section() -> None:
    payload = {
        "primary_suspect": "Shell Merchant LLC / acct_merch_gate_133",
        "laundering_volume": 88440.0,
        "narrative": (
            "Structuring and rapid pass-through of funds to high-risk jurisdictions; "
            "velocity inconsistent with stated business model."
        ),
        "confidence": 0.81,
    }
    pdf_bytes = sar_shadow_json_to_formal_pdf_bytes(payload)
    assert pdf_bytes.startswith(b"%PDF-")

    reader = PdfReader(io.BytesIO(pdf_bytes))
    text = "".join(page.extract_text() or "" for page in reader.pages)
    assert REGULATORY_SUMMARY_HEADING in text
    assert "Shell Merchant LLC" in text
    assert "88440" in text.replace(",", "") or "88,440" in text


def test_sar_pdf_rejects_incomplete_shadow_json() -> None:
    with pytest.raises(ValueError, match="missing required keys"):
        sar_shadow_json_to_formal_pdf_bytes({"primary_suspect": "x"})
