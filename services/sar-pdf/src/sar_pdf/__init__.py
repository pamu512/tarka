"""Regulatory document helpers (SAR PDF, hypothesis narrative, etc.)."""

from sar_pdf.pdf_generator import (
    REGULATORY_SUMMARY_HEADING,
    sar_shadow_json_to_formal_pdf_bytes,
)

__all__ = [
    "REGULATORY_SUMMARY_HEADING",
    "sar_shadow_json_to_formal_pdf_bytes",
]
