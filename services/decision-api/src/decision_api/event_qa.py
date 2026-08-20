"""Blind event-QA sampling from decision_audit (evaluate stream).

Separate loop from case-QA: samples individual *evaluate events* so a
human can confirm whether the engine decision was correct, without seeing
that decision up-front (blind review).

Schedule: env EVENT_QA_SAMPLE_N (default 20), EVENT_QA_CADENCE_HOURS
(default 24).  Drift-skip uses calibration drift + drift_promote_gate.
"""

from __future__ import annotations

import hashlib
import os
import uuid as _uuid_mod
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from decision_api.shared_path import ensure_services_shared_on_path

ensure_services_shared_on_path()
from auth_rbac import require_role  # noqa: E402

from decision_api.calibration_api import compute_drift_for_tenant  # noqa: E402
from decision_api.champion_challenger_audit import drift_promote_gate  # noqa: E402
from decision_api.db import get_session  # noqa: E402
from decision_api.models import AuditRecord  # noqa: E402
from decision_api.y_label_store import merge_y_labels  # noqa: E402

router = APIRouter(prefix="/v1/event-qa", tags=["event-qa"])

EVENT_QA_TAG = "qa:event_pending"
EVENT_QA_REVIEWED_PREFIX = "qa:event_"

_DEFAULT_SAMPLE_N = 20
_DEFAULT_CADENCE_HOURS = 24


def _sample_n() -> int:
    raw = os.environ.get("EVENT_QA_SAMPLE_N", "").strip()
    try:
        return max(1, min(int(raw), 500))
    except (ValueError, TypeError):
        return _DEFAULT_SAMPLE_N


def _cadence_hours() -> int:
    raw = os.environ.get("EVENT_QA_CADENCE_HOURS", "").strip()
    try:
        return max(1, min(int(raw), 8760))
    except (ValueError, TypeError):
        return _DEFAULT_CADENCE_HOURS


def _has_event_qa_tag(tags: list | None, prefix: str = "qa:event_") -> bool:
    return any(str(t).startswith(prefix) for t in (tags or []))


def _deterministic_sample(
    trace_ids: list[str], *, n: int, seed: str | None = None
) -> list[str]:
    """Stable hash-based sample of trace_ids (same algorithm as case QA)."""
    if not trace_ids:
        return []
    material = sorted(set(trace_ids))
    salt = (seed or datetime.now(UTC).strftime("%Y-%m-%d")).encode("utf-8")
    scored: list[tuple[float, str]] = []
    for tid in material:
        h = hashlib.sha256(salt + tid.encode("utf-8")).hexdigest()
        scored.append((int(h[:8], 16) / 0xFFFFFFFF, tid))
    scored.sort(key=lambda x: x[0])
    return [tid for _, tid in scored[: min(n, len(scored))]]


# ── Drift-skip check ──────────────────────────────────────────────


@router.get("/skip-check")
async def event_qa_skip_check(
    tenant_id: str = Query(..., min_length=1, max_length=128),
    profile: str = Query(default="default", max_length=64),
    _user=Depends(require_role("analyst")),
):
    """Check whether drift gates allow skipping the scheduled event-QA sample.

    Skip is allowed only when drift_promote_gate explicitly reports
    no drift — never when data is absent or the gate errors.
    """
    drift = compute_drift_for_tenant(tenant_id, profile)
    gate = drift_promote_gate(drift)
    hint = str(drift.get("hint") or "")

    # ponytail: skip only on explicit "no drift".  Absent data → must sample.
    skip_allowed = bool(gate.get("promote_allowed")) and hint not in {
        "no_reference_set",
        "no_snapshots_for_tenant",
        "empty_histograms",
        "insufficient_mass",
    }
    reason = hint if skip_allowed else f"drift_gate_blocks:{hint}"
    if not skip_allowed and not gate.get("promote_allowed"):
        reason = f"drift_elevated:{hint}"

    return {
        "schema_id": "tarka.event_qa_skip_check/v1",
        "tenant_id": tenant_id,
        "skip_allowed": skip_allowed,
        "reason": reason,
        "drift": drift,
        "drift_promote_gate": gate,
        "cadence_hours": _cadence_hours(),
        "sample_n": _sample_n(),
    }


# ── Sample ─────────────────────────────────────────────────────────


@router.post("/sample")
async def event_qa_sample(
    tenant_id: str = Query(..., min_length=1, max_length=128),
    n: int | None = Query(None, ge=1, le=500),
    seed: str | None = Query(None, max_length=64),
    session: AsyncSession = Depends(get_session),
    _user=Depends(require_role("analyst")),
):
    """Sample N evaluate events for blind QA review.

    Picks from AuditRecords that do NOT already have a qa:event_* tag.
    Tags selected rows with ``qa:event_pending``.
    """
    sample_n = n if n is not None else _sample_n()

    # Candidates: recent events without any qa:event_* tag, limited pool.
    cadence = _cadence_hours()
    since = datetime.now(UTC) - timedelta(hours=cadence * 7)
    stmt = (
        select(AuditRecord.trace_id)
        .where(
            AuditRecord.tenant_id == tenant_id,
            AuditRecord.created_at >= since,
        )
        .order_by(AuditRecord.created_at.desc())
        .limit(2000)
    )
    result = await session.execute(stmt)
    all_trace_ids: list[str] = []
    for (tid,) in result.all():
        all_trace_ids.append(str(tid))

    # Filter out rows that already have event QA tags (in Python — tags is JSON).
    if not all_trace_ids:
        eligible: list[str] = []
    else:
        uuid_list = [_uuid_mod.UUID(t) for t in all_trace_ids]
        eligible_stmt = (
            select(AuditRecord.trace_id, AuditRecord.tags)
            .where(
                AuditRecord.tenant_id == tenant_id,
                AuditRecord.trace_id.in_(uuid_list),
            )
        )
        eligible_result = await session.execute(eligible_stmt)
        eligible = [
            str(tid) for tid, tags in eligible_result.all()
            if not _has_event_qa_tag(tags)
        ]

    picked = _deterministic_sample(eligible, n=sample_n, seed=seed)

    # Tag selected rows.
    tagged = 0
    for tid_str in picked:
        try:
            tid_uuid = _uuid_mod.UUID(tid_str)
        except ValueError:
            continue
        row_result = await session.execute(
            select(AuditRecord).where(AuditRecord.trace_id == tid_uuid)
        )
        row = row_result.scalar_one_or_none()
        if row is None:
            continue
        tags = list(row.tags or [])
        if EVENT_QA_TAG not in tags:
            tags.append(EVENT_QA_TAG)
            row.tags = tags
            tagged += 1
    await session.commit()

    return {
        "schema_id": "tarka.event_qa_sample/v1",
        "tenant_id": tenant_id,
        "candidates": len(eligible),
        "sampled": len(picked),
        "tagged": tagged,
        "sample_n": sample_n,
        "seed": seed,
    }


# ── Pending (blind) ───────────────────────────────────────────────


@router.get("/pending")
async def event_qa_pending(
    tenant_id: str = Query(..., min_length=1, max_length=128),
    limit: int = Query(100, ge=1, le=500),
    session: AsyncSession = Depends(get_session),
    _user=Depends(require_role("analyst")),
):
    """List event-QA items awaiting blind review.

    Returns event metadata WITHOUT the original decision so the
    reviewer confirms independently (blind).
    """
    stmt = (
        select(AuditRecord)
        .where(AuditRecord.tenant_id == tenant_id)
        .order_by(AuditRecord.created_at.desc())
        .limit(2000)
    )
    result = await session.execute(stmt)
    records = result.scalars().all()

    items: list[dict[str, Any]] = []
    for rec in records:
        if EVENT_QA_TAG not in (rec.tags or []):
            continue
        # Already reviewed?
        if any(
            str(t).startswith("qa:event_agree") or str(t).startswith("qa:event_disagree")
            for t in (rec.tags or [])
        ):
            continue
        snap = rec.payload_snapshot if isinstance(rec.payload_snapshot, dict) else {}
        payload = snap.get("payload") if isinstance(snap.get("payload"), dict) else {}
        items.append({
            "trace_id": str(rec.trace_id),
            "entity_id": rec.entity_id,
            "event_type": rec.event_type,
            "score": rec.score,
            # Blind: expose payload context but NOT decision/rule_result/recommended_action.
            "amount": payload.get("amount"),
            "currency": payload.get("currency"),
            "created_at": rec.created_at.isoformat() if rec.created_at else None,
        })
        if len(items) >= limit:
            break

    return {
        "schema_id": "tarka.event_qa_pending/v1",
        "tenant_id": tenant_id,
        "count": len(items),
        "items": items,
    }


# ── Review (agree/disagree) ──────────────────────────────────────


class EventQaReviewBody(BaseModel):
    trace_id: str = Field(min_length=1, max_length=128)
    reviewer_decision: str = Field(
        min_length=1,
        max_length=32,
        description="Reviewer's independent verdict: allow / deny / review",
    )


@router.post("/review")
async def event_qa_review(
    body: EventQaReviewBody,
    tenant_id: str = Query(..., min_length=1, max_length=128),
    session: AsyncSession = Depends(get_session),
    _user=Depends(require_role("analyst")),
):
    """Submit blind review verdict for an evaluate event.

    Compares reviewer_decision to the original engine decision.
    Writes qa:event_agree or qa:event_disagree tag on the audit row,
    and merges a y_label into the durable y_label store for calibration.
    """
    try:
        tid = _uuid_mod.UUID(body.trace_id.strip())
    except ValueError as e:
        raise HTTPException(400, "trace_id must be a UUID") from e

    row_result = await session.execute(
        select(AuditRecord).where(AuditRecord.trace_id == tid)
    )
    row = row_result.scalar_one_or_none()
    if row is None or row.tenant_id != tenant_id:
        raise HTTPException(404, "audit event not found for tenant")

    tags = list(row.tags or [])
    if EVENT_QA_TAG not in tags:
        raise HTTPException(400, "event not in QA queue (missing qa:event_pending tag)")

    original_decision = (row.decision or "").strip().lower()
    reviewer = body.reviewer_decision.strip().lower()
    agree = original_decision == reviewer

    # Replace qa:event_pending with disposition tag.
    tags = [t for t in tags if t != EVENT_QA_TAG]
    tags.append("qa:event_agree" if agree else "qa:event_disagree")
    tags.append(f"qa:event_review:{reviewer}"[:64])
    row.tags = tags
    await session.commit()

    # Write y_label for calibration.
    # Convention: if reviewer says "deny" → FRAUD (1), "allow" → LEGITIMATE (0),
    # "review" → skip y_label (ambiguous).
    y_map = {"deny": "1", "allow": "0"}
    y_val = y_map.get(reviewer)
    y_label_written = False
    if y_val:
        merge_y_labels(
            tenant_id,
            by_trace={str(row.trace_id): y_val},
        )
        y_label_written = True

    return {
        "schema_id": "tarka.event_qa_review/v1",
        "trace_id": str(row.trace_id),
        "original_decision": original_decision,
        "reviewer_decision": reviewer,
        "agree": agree,
        "y_label_written": y_label_written,
    }


# ── Metrics ───────────────────────────────────────────────────────


@router.get("/metrics")
async def event_qa_metrics(
    tenant_id: str = Query(..., min_length=1, max_length=128),
    session: AsyncSession = Depends(get_session),
    _user=Depends(require_role("analyst")),
):
    """Agreement metrics for event-QA reviews."""
    stmt = (
        select(AuditRecord.tags)
        .where(AuditRecord.tenant_id == tenant_id)
        .order_by(AuditRecord.created_at.desc())
        .limit(5000)
    )
    result = await session.execute(stmt)

    pending = 0
    agree = 0
    disagree = 0
    for (tags,) in result.all():
        tag_set = set(tags or [])
        if EVENT_QA_TAG in tag_set:
            has_verdict = any(
                str(t).startswith("qa:event_agree") or str(t).startswith("qa:event_disagree")
                for t in tag_set
            )
            if not has_verdict:
                pending += 1
        if any(str(t).startswith("qa:event_agree") for t in tag_set):
            agree += 1
        if any(str(t).startswith("qa:event_disagree") for t in tag_set):
            disagree += 1

    reviewed = agree + disagree
    return {
        "schema_id": "tarka.event_qa_metrics/v1",
        "tenant_id": tenant_id,
        "pending": pending,
        "reviewed": reviewed,
        "agree": agree,
        "disagree": disagree,
        "agreement_rate": round(agree / reviewed, 4) if reviewed else None,
        "disagreement_rate": round(disagree / reviewed, 4) if reviewed else None,
        "cadence_hours": _cadence_hours(),
        "sample_n": _sample_n(),
    }


# ── Schedule info ─────────────────────────────────────────────────


@router.get("/schedule")
async def event_qa_schedule(
    _user=Depends(require_role("analyst")),
):
    """Current event-QA schedule configuration.

    Controlled by env vars ``EVENT_QA_SAMPLE_N`` and
    ``EVENT_QA_CADENCE_HOURS``.  A cron job or the desk UI triggers
    ``POST /v1/event-qa/sample`` at this cadence.
    """
    return {
        "schema_id": "tarka.event_qa_schedule/v1",
        "sample_n": _sample_n(),
        "cadence_hours": _cadence_hours(),
        "env": {
            "EVENT_QA_SAMPLE_N": os.environ.get("EVENT_QA_SAMPLE_N", "(unset → 20)"),
            "EVENT_QA_CADENCE_HOURS": os.environ.get(
                "EVENT_QA_CADENCE_HOURS", "(unset → 24)"
            ),
        },
        "cron_example": f"0 */{_cadence_hours()} * * * curl -X POST .../v1/event-qa/sample?tenant_id=...",
    }
