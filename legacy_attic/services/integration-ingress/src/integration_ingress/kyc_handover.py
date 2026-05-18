"""KYC handover — request additional ID via automated user email (Prompt 186)."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from typing import Any

DEFAULT_DOCUMENTS = [
    "government_id_front",
    "government_id_back",
    "proof_of_address",
]
EMAIL_TEMPLATE_ID = "kyc_additional_id_v1"


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


_SENT_BY_CASE: dict[str, dict[str, Any]] = {}


def _case_key(tenant_id: str, case_id: str) -> str:
    return f"{tenant_id.strip()}:{case_id.strip()}"


def _demo_cases(tenant_id: str) -> list[dict[str, Any]]:
    tid = tenant_id
    seeds = [
        ("c1", "user_alice", "alice@example-retail.com", "Alice Johnson", 9200, True),
        ("c2", "user_bob", "bob.pending@maildrop.demo", "Bob Chen", 15000, True),
        ("c3", "user_carol", "carol.k@example.com", "Carol Okonkwo", 2400, False),
        ("c4", "fraud_frank", "frank.moretti@burner.io", "Frank Moretti", 48000, True),
        ("c5", "user_eve", "eve.m@example.com", "Eve Martinez", 11000, True),
    ]
    rows: list[dict[str, Any]] = []
    for case_id, uid, email, name, amount, needs_id in seeds:
        key = _case_key(tid, case_id)
        sent = _SENT_BY_CASE.get(key)
        status = "needs_more_id" if needs_id else "verified"
        handover = "not_required"
        if needs_id:
            handover = "email_sent" if sent else "pending"
        rows.append(
            {
                "case_id": case_id,
                "tenant_id": tid,
                "subject_user_id": uid,
                "subject_email": email,
                "display_name": name,
                "case_title": f"Case {case_id.upper()} — ${amount:,} review",
                "kyc_status": status,
                "documents_requested": list(DEFAULT_DOCUMENTS) if needs_id else [],
                "handover_status": handover,
                "email_sent_at": sent.get("sent_at") if sent else None,
                "email_message_id": sent.get("message_id") if sent else None,
                "email_template_id": sent.get("template_id") if sent else None,
                "email_subject": sent.get("subject") if sent else None,
                "amount_usd": amount,
                "priority": "high" if amount >= 10000 else "normal",
            },
        )
    return rows


def get_kyc_handover_for_case(*, tenant_id: str, case_id: str) -> dict[str, Any] | None:
    for row in _demo_cases(tenant_id):
        if row["case_id"] == case_id:
            return dict(row)
    return None


def send_kyc_id_request_email(
    *,
    tenant_id: str,
    case_id: str,
    analyst_note: str | None = None,
) -> dict[str, Any]:
    tid = (tenant_id or "demo").strip() or "demo"
    cid = case_id.strip()
    row = get_kyc_handover_for_case(tenant_id=tid, case_id=cid)
    if row is None:
        return {"ok": False, "error": "case_not_found", "case_id": cid}
    if row["kyc_status"] != "needs_more_id":
        return {
            "ok": False,
            "error": "kyc_not_pending",
            "case_id": cid,
            "kyc_status": row["kyc_status"],
        }

    sent_at = _now_iso()
    message_id = f"msg_{hashlib.sha256(f'{tid}:{cid}:{sent_at}'.encode()).hexdigest()[:16]}"
    subject = "Action required: additional identity verification"
    email_payload = {
        "message_id": message_id,
        "sent_at": sent_at,
        "to": row["subject_email"],
        "template_id": EMAIL_TEMPLATE_ID,
        "subject": subject,
        "analyst_note": (analyst_note or "").strip() or None,
        "documents_requested": row["documents_requested"],
        "upload_deadline_hours": 72,
    }
    key = _case_key(tid, cid)
    _SENT_BY_CASE[key] = email_payload

    updated = dict(row)
    updated["handover_status"] = "email_sent"
    updated["email_sent_at"] = sent_at
    updated["email_message_id"] = message_id
    updated["email_template_id"] = EMAIL_TEMPLATE_ID
    updated["email_subject"] = subject

    return {
        "ok": True,
        "case_id": cid,
        "tenant_id": tid,
        "email": email_payload,
        "handover": updated,
    }


def build_kyc_handover_board(
    *,
    tenant_id: str,
    case_id: str | None = None,
) -> dict[str, Any]:
    tid = (tenant_id or "demo").strip() or "demo"
    rows = _demo_cases(tid)
    if case_id:
        rows = [r for r in rows if r["case_id"] == case_id.strip()]

    pending = [r for r in rows if r["handover_status"] == "pending"]
    sent = [r for r in rows if r["handover_status"] == "email_sent"]
    needs = [r for r in rows if r["kyc_status"] == "needs_more_id"]

    return {
        "tenant_id": tid,
        "updated_at": _now_iso(),
        "source": "demo_aggregate",
        "email_template_id": EMAIL_TEMPLATE_ID,
        "default_documents_requested": DEFAULT_DOCUMENTS,
        "summary": {
            "needs_more_id_count": len(needs),
            "pending_email_count": len(pending),
            "email_sent_count": len(sent),
        },
        "cases": sorted(
            rows,
            key=lambda r: (
                0 if r["handover_status"] == "pending" else 1,
                -int(r.get("amount_usd") or 0),
                str(r["case_id"]),
            ),
        ),
    }
