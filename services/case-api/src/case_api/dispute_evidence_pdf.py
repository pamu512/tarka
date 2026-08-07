"""Minimal chargeback / dispute evidence PDF (stdlib only — no reportlab)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any


def _pdf_escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def build_dispute_evidence_pdf_bytes(*, dispute: dict[str, Any]) -> bytes:
    """Build a single-page text PDF summarizing dispute representment fields."""
    lines = [
        "Tarka dispute evidence package",
        f"Generated (UTC): {datetime.now(UTC).isoformat()}",
        "",
        f"dispute_id: {dispute.get('id')}",
        f"tenant_id: {dispute.get('tenant_id')}",
        f"entity_id: {dispute.get('entity_id')}",
        f"trace_id: {dispute.get('trace_id')}",
        f"case_id: {dispute.get('case_id')}",
        f"dispute_type: {dispute.get('dispute_type')}",
        f"status: {dispute.get('status')}",
        f"reason_code: {dispute.get('reason_code')}",
        f"amount: {dispute.get('amount')} {dispute.get('currency')}",
        f"merchant_id: {dispute.get('merchant_id')}",
        f"card_network: {dispute.get('card_network')}",
        f"original_decision: {dispute.get('original_decision')}",
        f"original_score: {dispute.get('original_score')}",
        f"original_rule_hits: {dispute.get('original_rule_hits')}",
        f"outcome: {dispute.get('outcome')}",
        f"filed_at: {dispute.get('filed_at')}",
        f"resolved_at: {dispute.get('resolved_at')}",
        f"provider_response_deadline_at: {dispute.get('provider_response_deadline_at')}",
        "",
        "Notes: Generated from case-api dispute records for analyst review.",
        "Lifecycle graph diagrams remain available via orchestrator file-dispute when linked.",
    ]
    content_ops = ["BT", "/F1 10 Tf", "50 750 Td", "14 TL"]
    for i, line in enumerate(lines[:55]):
        esc = _pdf_escape(str(line)[:110])
        if i == 0:
            content_ops.append(f"({esc}) Tj")
        else:
            content_ops.extend(["T*", f"({esc}) Tj"])
    content_ops.append("ET")
    stream = "\n".join(content_ops).encode("latin-1", errors="replace")

    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            b"/Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>"
        ),
        b"<< /Length " + str(len(stream)).encode("ascii") + b" >>\nstream\n" + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]

    out = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for i, obj in enumerate(objects, start=1):
        offsets.append(len(out))
        out.extend(f"{i} 0 obj\n".encode("ascii"))
        out.extend(obj)
        out.extend(b"\nendobj\n")

    xref_pos = len(out)
    out.extend(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
    out.extend(b"0000000000 65535 f \n")
    for off in offsets[1:]:
        out.extend(f"{off:010d} 00000 n \n".encode("ascii"))
    out.extend(
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref_pos}\n%%EOF\n".encode(
            "ascii"
        )
    )
    return bytes(out)
