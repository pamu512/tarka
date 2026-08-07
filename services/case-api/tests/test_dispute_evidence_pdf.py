"""Unit: dispute evidence PDF bytes are valid and include dispute fields."""

from __future__ import annotations

import uuid

from case_api.dispute_evidence_pdf import build_dispute_evidence_pdf_bytes
from case_api.schemas import DisputeOut


def test_build_dispute_evidence_pdf_starts_with_pdf_header() -> None:
    dispute_id = uuid.uuid4()
    body = build_dispute_evidence_pdf_bytes(
        dispute={
            "id": str(dispute_id),
            "tenant_id": "t1",
            "entity_id": "e1",
            "trace_id": "tr1",
            "dispute_type": "chargeback",
            "status": "filed",
            "reason_code": "10.4",
            "amount": 42.5,
            "currency": "USD",
        }
    )
    assert body.startswith(b"%PDF-")
    assert b"chargeback" in body
    assert str(dispute_id).encode("ascii") in body


def test_dispute_out_computes_evidence_pdf_url() -> None:
    dispute_id = uuid.uuid4()
    out = DisputeOut(
        id=dispute_id,
        case_id=None,
        tenant_id="t1",
        entity_id="e1",
        trace_id="tr1",
        dispute_type="chargeback",
        status="filed",
        reason_code="10.4",
        amount=1.0,
        currency="USD",
        merchant_id=None,
        card_network=None,
        original_decision=None,
        original_score=None,
        original_rule_hits=[],
        original_ml_score=None,
        outcome=None,
        resolution_notes=None,
        filed_at=None,
        resolved_at=None,
        created_at=None,
        updated_at=None,
    )
    assert out.evidence_pdf_url == f"/api/cases/v1/disputes/{dispute_id}/evidence-pdf"
