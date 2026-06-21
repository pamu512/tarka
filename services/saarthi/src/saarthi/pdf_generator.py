"""Convert Shadow ``SARReportSchema``-shaped JSON into a formal SAR-style PDF (ReportLab)."""

from __future__ import annotations

import io
from collections.abc import Mapping
from typing import Any
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

# Gate-visible section title (must match PDF text extraction).
REGULATORY_SUMMARY_HEADING = "Regulatory Summary"

_REQUIRED_KEYS = frozenset({"primary_suspect", "laundering_volume", "narrative", "confidence"})


def _require_sar_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    missing = _REQUIRED_KEYS - frozenset(payload.keys())
    if missing:
        raise ValueError(f"SAR JSON missing required keys: {sorted(missing)}")
    return dict(payload)


def sar_shadow_json_to_formal_pdf_bytes(
    payload: Mapping[str, Any],
    *,
    currency: str = "USD",
) -> bytes:
    """
    Build a single-file SAR draft PDF from Shadow JSON (``primary_suspect``, ``laundering_volume``,
    ``narrative``, ``confidence``).

    The document includes a **Regulatory Summary** section suitable for compliance review.
    """
    data = _require_sar_payload(payload)
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=letter,
        rightMargin=inch * 0.75,
        leftMargin=inch * 0.75,
        topMargin=inch * 0.75,
        bottomMargin=inch * 0.75,
        title="Suspicious Activity Report (SAR) — Draft",
    )
    styles = getSampleStyleSheet()
    h1 = ParagraphStyle("SARH1", parent=styles["Heading1"], fontSize=16, spaceAfter=14)
    h2 = ParagraphStyle(
        "SARH2",
        parent=styles["Heading2"],
        fontSize=12,
        spaceAfter=8,
        textColor=colors.HexColor("#1a5276"),
    )
    body = ParagraphStyle("SARBody", parent=styles["Normal"], fontSize=10, leading=14)

    suspect = str(data["primary_suspect"])
    volume = float(data["laundering_volume"])
    narrative = str(data["narrative"])
    confidence = float(data["confidence"])

    story: list[Any] = [
        Paragraph("Suspicious Activity Report (SAR)", h1),
        Paragraph(
            "<i>Draft generated from structured Shadow analyst output. "
            "File separately per FinCEN / jurisdictional instructions.</i>",
            styles["Normal"],
        ),
        Spacer(1, 0.2 * inch),
        Paragraph("Structured findings", h2),
        Table(
            [
                ["Field", "Value"],
                ["Primary suspect / subject", suspect[:500] + ("…" if len(suspect) > 500 else "")],
                [f"Estimated laundering volume ({currency})", f"{volume:,.2f}"],
                ["Model confidence (0–1)", f"{confidence:.4f}"],
            ],
            colWidths=[2.1 * inch, 4.4 * inch],
            style=TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#ecf0f1")),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("FONTSIZE", (0, 0), (-1, -1), 9),
                    ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 6),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                    ("TOPPADDING", (0, 0), (-1, -1), 4),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ],
            ),
        ),
        Spacer(1, 0.18 * inch),
        Paragraph("Narrative (factual basis)", h2),
        Paragraph(escape(narrative), body),
        Spacer(1, 0.22 * inch),
        Paragraph(REGULATORY_SUMMARY_HEADING, h2),
        Paragraph(
            (
                "This summary restates the structured filing posture for supervisory review: "
                f"the reported subject is <b>{escape(suspect[:180])}{'…' if len(suspect) > 180 else ''}</b>; "
                f"aggregate suspicious movement is estimated at <b>{escape(f'{volume:,.2f} {currency}')}</b> with "
                f"analytic confidence <b>{escape(f'{confidence:.0%}')}</b>. "
                "The narrative section above must be reviewed for completeness, accuracy, and "
                "timeliness before BSA e-filing or equivalent submission. "
                "No filing is implied by this draft PDF alone."
            ),
            body,
        ),
    ]
    doc.build(story)
    return buf.getvalue()
