"""Dispute and chargeback automation with rules/ML feedback loop."""

import logging
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from case_api.config import settings
from case_api.db import get_session
from case_api.models import Case, CaseComment, Dispute
from case_api.schemas import CreateDisputeRequest, DisputeOut, UpdateDisputeRequest

_shared = Path(__file__).resolve().parents[3] / "shared"
if str(_shared) not in sys.path:
    sys.path.insert(0, str(_shared))
from auth_rbac import require_role  # noqa: E402

log = logging.getLogger(__name__)
router = APIRouter(prefix="/v1/disputes", tags=["disputes"])

VALID_DISPUTE_TYPES = {"chargeback", "dispute", "fraud_claim", "unauthorized", "service_not_rendered", "product_not_received"}
VALID_STATUSES = {"filed", "investigating", "evidence_submitted", "accepted", "rejected", "resolved"}
VALID_OUTCOMES = {"fraud_confirmed", "false_positive", "inconclusive", "merchant_fault", "customer_fault"}


async def _fetch_original_decision(http: httpx.AsyncClient, trace_id: str) -> dict[str, Any]:
    """Fetch the original decision audit record from the decision-api."""
    decision_url = settings.decision_api_url if hasattr(settings, "decision_api_url") and settings.decision_api_url else None
    if not decision_url:
        return {}
    try:
        r = await http.get(f"{decision_url.rstrip('/')}/v1/audit/{trace_id}", timeout=5.0)
        if r.status_code == 200:
            return r.json()
    except Exception as e:
        log.warning("Failed to fetch original decision for trace %s: %s", trace_id, e)
    return {}


async def _tag_entity(http: httpx.AsyncClient, tenant_id: str, entity_id: str, tags: list[str]) -> None:
    """Push tags to both Redis (via decision-api) and Neo4j (via graph-service)."""
    if settings.graph_service_url:
        try:
            await http.post(
                f"{settings.graph_service_url.rstrip('/')}/v1/entities/{entity_id}/tags",
                json={"tenant_id": tenant_id, "tags": tags},
                timeout=3.0,
            )
        except Exception as e:
            log.warning("Failed to tag entity %s in graph: %s", entity_id, e)


async def _send_ml_feedback(http: httpx.AsyncClient, dispute: Dispute) -> None:
    """Send dispute outcome as ML training label feedback."""
    ml_url = settings.ml_scoring_url if hasattr(settings, "ml_scoring_url") and settings.ml_scoring_url else None
    if not ml_url or not dispute.outcome:
        return
    is_fraud = dispute.outcome in ("fraud_confirmed", "merchant_fault")
    try:
        await http.post(
            f"{ml_url.rstrip('/')}/v1/feedback",
            json={
                "tenant_id": dispute.tenant_id,
                "entity_id": dispute.entity_id,
                "trace_id": dispute.trace_id,
                "label": "fraud" if is_fraud else "legitimate",
                "source": "dispute",
                "dispute_type": dispute.dispute_type,
                "outcome": dispute.outcome,
            },
            timeout=3.0,
        )
    except Exception as e:
        log.warning("Failed to send ML feedback for dispute %s: %s", dispute.id, e)


def _compute_dispute_tags(dispute_type: str, status: str, outcome: str | None) -> list[str]:
    """Generate real-time tags based on dispute lifecycle."""
    tags = [f"dispute:{dispute_type}", f"dispute:status:{status}"]
    if status == "filed":
        tags.append("dispute:active")
    if outcome:
        tags.append(f"dispute:outcome:{outcome}")
        if outcome == "fraud_confirmed":
            tags.append("confirmed_fraud")
        elif outcome == "false_positive":
            tags.append("dispute:false_positive")
    return tags


@router.post("", response_model=DisputeOut, status_code=201)
async def create_dispute(
    body: CreateDisputeRequest,
    request: Request,
    session: AsyncSession = Depends(get_session),
    _user=Depends(require_role("analyst")),
):
    """File a new dispute or chargeback, auto-linking to the original decision."""
    if body.dispute_type not in VALID_DISPUTE_TYPES:
        raise HTTPException(400, f"Invalid dispute_type. Must be one of: {', '.join(sorted(VALID_DISPUTE_TYPES))}")

    http: httpx.AsyncClient = request.app.state.http

    original = await _fetch_original_decision(http, body.trace_id)

    case_id = None
    if body.case_id:
        try:
            case_id = uuid.UUID(body.case_id)
        except ValueError:
            raise HTTPException(400, "Invalid case_id format")
    elif original:
        case = Case(
            tenant_id=body.tenant_id,
            title=f"{body.dispute_type.replace('_', ' ').title()}: {body.entity_id}",
            entity_id=body.entity_id,
            trace_id=body.trace_id,
            priority="high" if body.amount >= 500 else "medium",
            status="investigating",
            labels=["dispute", body.dispute_type],
        )
        session.add(case)
        await session.flush()
        case_id = case.id
        session.add(
            CaseComment(
                case_id=case.id,
                author="system:dispute-engine",
                body=f"Auto-created from {body.dispute_type} filing. Amount: {body.currency} {body.amount:.2f}. Trace: {body.trace_id}",
            )
        )

    dispute = Dispute(
        tenant_id=body.tenant_id,
        entity_id=body.entity_id,
        trace_id=body.trace_id,
        case_id=case_id,
        dispute_type=body.dispute_type,
        status="filed",
        reason_code=body.reason_code,
        amount=body.amount,
        currency=body.currency,
        merchant_id=body.merchant_id,
        card_network=body.card_network,
        original_decision=original.get("decision"),
        original_score=original.get("score"),
        original_rule_hits=original.get("rule_hits", []),
        original_ml_score=None,
    )
    session.add(dispute)
    await session.commit()
    await session.refresh(dispute)

    tags = _compute_dispute_tags(body.dispute_type, "filed", None)
    await _tag_entity(http, body.tenant_id, body.entity_id, tags)

    return DisputeOut.model_validate(dispute)


@router.get("", response_model=dict)
async def list_disputes(
    tenant_id: str,
    session: AsyncSession = Depends(get_session),
    status: str | None = None,
    dispute_type: str | None = None,
    entity_id: str | None = None,
    limit: int = 50,
):
    """List disputes with optional filters."""
    q = select(Dispute).where(Dispute.tenant_id == tenant_id)
    if status:
        q = q.where(Dispute.status == status)
    if dispute_type:
        q = q.where(Dispute.dispute_type == dispute_type)
    if entity_id:
        q = q.where(Dispute.entity_id == entity_id)
    q = q.order_by(Dispute.created_at.desc()).limit(min(limit, 200))
    result = await session.execute(q)
    rows = result.scalars().all()
    return {"items": [DisputeOut.model_validate(r).model_dump() for r in rows]}


@router.get("/stats")
async def dispute_stats(tenant_id: str, session: AsyncSession = Depends(get_session)):
    """Aggregate dispute statistics for dashboard."""
    base = select(Dispute).where(Dispute.tenant_id == tenant_id)
    total = await session.execute(select(func.count()).select_from(base.subquery()))
    total_count = total.scalar() or 0

    by_status = await session.execute(select(Dispute.status, func.count()).where(Dispute.tenant_id == tenant_id).group_by(Dispute.status))
    status_counts = {row[0]: row[1] for row in by_status.all()}

    by_type = await session.execute(select(Dispute.dispute_type, func.count()).where(Dispute.tenant_id == tenant_id).group_by(Dispute.dispute_type))
    type_counts = {row[0]: row[1] for row in by_type.all()}

    by_outcome = await session.execute(
        select(Dispute.outcome, func.count()).where(Dispute.tenant_id == tenant_id, Dispute.outcome.isnot(None)).group_by(Dispute.outcome)
    )
    outcome_counts = {row[0]: row[1] for row in by_outcome.all()}

    total_amount = await session.execute(select(func.sum(Dispute.amount)).where(Dispute.tenant_id == tenant_id))
    sum_amount = total_amount.scalar() or 0.0

    won = outcome_counts.get("fraud_confirmed", 0) + outcome_counts.get("merchant_fault", 0)
    lost = outcome_counts.get("false_positive", 0) + outcome_counts.get("customer_fault", 0)
    win_rate = won / (won + lost) if (won + lost) > 0 else 0.0

    return {
        "total": total_count,
        "by_status": status_counts,
        "by_type": type_counts,
        "by_outcome": outcome_counts,
        "total_amount": sum_amount,
        "win_rate": win_rate,
    }


@router.get("/{dispute_id}", response_model=DisputeOut)
async def get_dispute(dispute_id: uuid.UUID, session: AsyncSession = Depends(get_session)):
    result = await session.execute(select(Dispute).where(Dispute.id == dispute_id))
    row = result.scalar_one_or_none()
    if not row:
        raise HTTPException(404, "Dispute not found")
    return DisputeOut.model_validate(row)


@router.patch("/{dispute_id}", response_model=DisputeOut)
async def update_dispute(
    dispute_id: uuid.UUID,
    body: UpdateDisputeRequest,
    request: Request,
    session: AsyncSession = Depends(get_session),
    _user=Depends(require_role("analyst")),
):
    """Update dispute status/outcome. Triggers real-time tags and ML feedback."""
    result = await session.execute(select(Dispute).where(Dispute.id == dispute_id))
    dispute = result.scalar_one_or_none()
    if not dispute:
        raise HTTPException(404, "Dispute not found")

    if body.status:
        if body.status not in VALID_STATUSES:
            raise HTTPException(400, f"Invalid status. Must be one of: {', '.join(sorted(VALID_STATUSES))}")
        dispute.status = body.status

    if body.outcome:
        if body.outcome not in VALID_OUTCOMES:
            raise HTTPException(400, f"Invalid outcome. Must be one of: {', '.join(sorted(VALID_OUTCOMES))}")
        dispute.outcome = body.outcome
        dispute.resolved_at = datetime.now(timezone.utc)
        dispute.status = "resolved"

    if body.resolution_notes is not None:
        dispute.resolution_notes = body.resolution_notes

    await session.commit()
    await session.refresh(dispute)

    http: httpx.AsyncClient = request.app.state.http

    tags = _compute_dispute_tags(dispute.dispute_type, dispute.status, dispute.outcome)
    await _tag_entity(http, dispute.tenant_id, dispute.entity_id, tags)

    if dispute.outcome:
        await _send_ml_feedback(http, dispute)

        if dispute.case_id:
            case_result = await session.execute(select(Case).where(Case.id == dispute.case_id))
            case = case_result.scalar_one_or_none()
            if case:
                if dispute.outcome == "fraud_confirmed":
                    if "confirmed_fraud" not in (case.labels or []):
                        case.labels = sorted(set(case.labels or []) | {"confirmed_fraud", "dispute_resolved"})
                    case.priority = "critical"
                elif dispute.outcome == "false_positive":
                    case.labels = sorted(set(case.labels or []) | {"false_positive", "dispute_resolved"})
                else:
                    case.labels = sorted(set(case.labels or []) | {"dispute_resolved"})
                session.add(
                    CaseComment(
                        case_id=dispute.case_id,
                        author="system:dispute-engine",
                        body=f"Dispute resolved: {dispute.outcome}. {dispute.resolution_notes or ''}",
                    )
                )
                await session.commit()

    return DisputeOut.model_validate(dispute)


@router.get("/{dispute_id}/original-decision")
async def get_original_decision(
    dispute_id: uuid.UUID,
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    """Retrieve the original fraud decision that led to this dispute."""
    result = await session.execute(select(Dispute).where(Dispute.id == dispute_id))
    dispute = result.scalar_one_or_none()
    if not dispute:
        raise HTTPException(404, "Dispute not found")

    http: httpx.AsyncClient = request.app.state.http
    original = await _fetch_original_decision(http, dispute.trace_id)

    return {
        "dispute_id": str(dispute.id),
        "trace_id": dispute.trace_id,
        "original_decision": original
        if original
        else {
            "decision": dispute.original_decision,
            "score": dispute.original_score,
            "rule_hits": dispute.original_rule_hits,
        },
    }


@router.get("/entity/{entity_id}/history")
async def entity_dispute_history(
    entity_id: str,
    tenant_id: str,
    session: AsyncSession = Depends(get_session),
):
    """Get all disputes for an entity — feeds into risk assessment."""
    result = await session.execute(select(Dispute).where(Dispute.tenant_id == tenant_id, Dispute.entity_id == entity_id).order_by(Dispute.created_at.desc()))
    rows = result.scalars().all()
    fraud_count = sum(1 for r in rows if r.outcome == "fraud_confirmed")
    false_pos_count = sum(1 for r in rows if r.outcome == "false_positive")
    total_amount = sum(r.amount for r in rows)

    return {
        "entity_id": entity_id,
        "total_disputes": len(rows),
        "fraud_confirmed_count": fraud_count,
        "false_positive_count": false_pos_count,
        "total_disputed_amount": total_amount,
        "risk_indicator": "high" if fraud_count >= 3 else "medium" if fraud_count >= 1 else "low",
        "disputes": [DisputeOut.model_validate(r).model_dump() for r in rows],
    }
