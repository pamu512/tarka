"""Batch training-label lookup for ML export (disputes + case labels, keyed by ``trace_id``)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from case_api.db import get_session
from case_api.models import Case, Dispute

import sys
from pathlib import Path

_shared = Path(__file__).resolve().parents[3] / "shared"
if str(_shared) not in sys.path:
    sys.path.insert(0, str(_shared))
from auth_rbac import require_role  # noqa: E402

router = APIRouter(prefix="/v1/ml", tags=["ml-training"])

_MAX_TRACE_IDS = 2_000


def _dispute_to_training_label(outcome: str) -> tuple[str, str]:
    """Return ``(case_management_label, dispute_outcome)``."""
    o = (outcome or "").strip().lower()
    if o in ("fraud_confirmed", "merchant_fault"):
        return "fraud", o
    if o in ("false_positive", "customer_fault"):
        return "not_fraud", o
    if o in ("inconclusive",):
        return "unknown", o
    return "unknown", o


def _case_labels_to_training_label(labels: list[Any] | None) -> str | None:
    if not labels:
        return None
    s = {str(x).strip().lower() for x in labels if str(x).strip()}
    if "confirmed_fraud" in s:
        return "fraud"
    if "false_positive" in s:
        return "not_fraud"
    return None


class TrainingLabelsByTraceIn(BaseModel):
    tenant_id: str = Field(..., min_length=1, max_length=128)
    trace_ids: list[str] = Field(..., min_length=1)


class TrainingLabelsByTraceOut(BaseModel):
    """Per-trace supervision bundle (no feature payloads — those stay in the analytics warehouse)."""

    labels: dict[str, dict[str, Any]]


@router.post("/training-labels/by-trace", response_model=TrainingLabelsByTraceOut)
async def training_labels_by_trace(
    body: TrainingLabelsByTraceIn,
    session: AsyncSession = Depends(get_session),
    _user=Depends(require_role("analyst")),
) -> TrainingLabelsByTraceOut:
    if len(body.trace_ids) > _MAX_TRACE_IDS:
        raise HTTPException(400, f"trace_ids must be at most {_MAX_TRACE_IDS}")
    cleaned = [t.strip() for t in body.trace_ids if t and str(t).strip()]
    if not cleaned:
        raise HTTPException(400, "trace_ids must contain at least one non-empty id")

    tid = body.tenant_id.strip()
    out: dict[str, dict[str, Any]] = {t: {} for t in cleaned}

    stmt = (
        select(Dispute.trace_id, Dispute.outcome, Dispute.resolved_at)
        .where(
            Dispute.tenant_id == tid,
            Dispute.trace_id.in_(cleaned),
            Dispute.outcome.isnot(None),
        )
        .order_by(desc(Dispute.resolved_at).nulls_last())
    )
    result = await session.execute(stmt)
    dispute_seen: set[str] = set()
    for trace_id, outcome, resolved_at in result.all():
        tr = str(trace_id or "").strip()
        if not tr or tr in dispute_seen:
            continue
        oc = str(outcome or "").strip()
        if not oc:
            continue
        dispute_seen.add(tr)
        label, raw_o = _dispute_to_training_label(oc)
        out[tr] = {
            "case_management_label": label,
            "case_label_source": "dispute",
            "dispute_outcome": raw_o,
            "label_resolved_at": resolved_at.isoformat() if resolved_at else None,
        }

    missing = [t for t in cleaned if not out[t]]
    if missing:
        cr = await session.execute(
            select(Case.trace_id, Case.labels).where(
                Case.tenant_id == tid, Case.trace_id.in_(missing)
            )
        )
        case_seen: set[str] = set()
        for trace_id, labels in cr.all():
            tr = str(trace_id or "").strip()
            if not tr or tr in case_seen:
                continue
            case_seen.add(tr)
            mapped = _case_labels_to_training_label(list(labels or []))
            if mapped and not out[tr]:
                out[tr] = {
                    "case_management_label": mapped,
                    "case_label_source": "case_labels",
                    "dispute_outcome": "",
                    "label_resolved_at": None,
                }

    for t in cleaned:
        if not out[t]:
            out[t] = {
                "case_management_label": "unknown",
                "case_label_source": "none",
                "dispute_outcome": "",
                "label_resolved_at": None,
            }

    return TrainingLabelsByTraceOut(labels=out)
