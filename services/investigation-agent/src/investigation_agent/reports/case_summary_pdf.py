from __future__ import annotations

from datetime import datetime, timezone
from io import BytesIO
from typing import Any

from fpdf import FPDF

"""Case summary PDF from structured answer_sections + reply (no LLM)."""


def _safe_pdf_text(s: str) -> str:
    """FPDF core fonts: approximate Latin-1; replace unsupported chars."""
    if not s:
        return ""
    return s.encode("latin-1", errors="replace").decode("latin-1")


def render_case_summary_pdf(
    *,
    title: str,
    reply: str,
    answer_sections: dict[str, Any],
    claims: list[dict[str, str]] | None,
    case_id: str | None,
    turn_id: str | None,
    prompt_version: str | None,
    workflow_id: str | None,
) -> bytes:
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()
    col_w = float(getattr(pdf, "epw", pdf.w - pdf.l_margin - pdf.r_margin))
    pdf.set_font("Helvetica", "B", 16)
    pdf.multi_cell(col_w, 10, _safe_pdf_text(title or "Case summary"))
    pdf.set_font("Helvetica", "", 9)
    pdf.ln(2)
    meta_parts = [
        f"Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
    ]
    if case_id:
        meta_parts.append(f"case_id: {case_id}")
    if turn_id:
        meta_parts.append(f"turn_id: {turn_id}")
    if prompt_version:
        meta_parts.append(f"prompt_version: {prompt_version}")
    if workflow_id:
        meta_parts.append(f"workflow_id: {workflow_id}")
    pdf.multi_cell(col_w, 5, _safe_pdf_text(" | ".join(meta_parts)))
    pdf.ln(4)

    sections = answer_sections if isinstance(answer_sections, dict) else {}
    order = [
        ("preamble", "Overview"),
        ("facts_from_tools", "FACTS FROM TOOLS"),
        ("inferences", "INFERENCES"),
        ("unknowns", "UNKNOWNS"),
        ("next_steps", "NEXT STEPS"),
    ]
    pdf.set_font("Helvetica", "B", 11)
    pdf.multi_cell(col_w, 7, _safe_pdf_text("Assistant reply (full text)"))
    pdf.set_font("Helvetica", "", 10)
    pdf.multi_cell(col_w, 5, _safe_pdf_text(reply.strip() or "-"))
    pdf.ln(3)

    for key, heading in order:
        val = sections.get(key)
        if not val or not str(val).strip():
            continue
        pdf.set_font("Helvetica", "B", 11)
        pdf.multi_cell(col_w, 7, _safe_pdf_text(heading))
        pdf.set_font("Helvetica", "", 10)
        pdf.multi_cell(col_w, 5, _safe_pdf_text(str(val).strip()))
        pdf.ln(2)

    if claims:
        pdf.set_font("Helvetica", "B", 11)
        pdf.multi_cell(col_w, 7, _safe_pdf_text("Claims (trailer)"))
        pdf.set_font("Helvetica", "", 9)
        for c in claims[:40]:
            if not isinstance(c, dict):
                continue
            t = str(c.get("text", "")).strip()
            src = str(c.get("source", "")).strip()
            if t:
                pdf.multi_cell(col_w, 4, _safe_pdf_text(f"* [{src}] {t[:500]}"))
        pdf.ln(2)

    pdf.set_font("Helvetica", "I", 8)
    pdf.multi_cell(
        col_w,
        4,
        _safe_pdf_text("Draft for human review. Provenance: client-supplied chat fields; not a legal or regulatory attestation."),
    )
    buf = BytesIO()
    pdf.output(buf)
    return buf.getvalue()
