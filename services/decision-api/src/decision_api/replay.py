from __future__ import annotations

import logging
import uuid as uuid_lib
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from decision_api.db import get_session
from decision_api.json_rules import _match_condition
from decision_api.models import AuditRecord

"""Event replay / backtesting router.

Allows analysts to re-evaluate historical events through the rules engine
with overridden rules, comparing the original decision to the new one.
"""
log = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/replay", tags=["replay"])


class ReplayCondition(BaseModel):
    field: str
    op: str = "eq"
    value: Any = None


class ReplayRule(BaseModel):
    id: str = ""
    when: list[ReplayCondition] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    score_delta: float = 0
    description: str = ""


class ReplayRequest(BaseModel):
    tenant_id: str
    rules_override: list[ReplayRule] = Field(default_factory=list)
    limit: int = Field(default=100, ge=1, le=5000)
    trace_ids: list[str] = Field(
        default_factory=list,
        max_length=200,
        description="When non-empty, replay these audits (tenant-scoped) in order; limit is ignored.",
    )


class ReplayResultItem(BaseModel):
    trace_id: str
    entity_id: str
    event_type: str
    original_decision: str
    original_score: float
    original_rule_hits: list[str]
    new_decision: str
    new_score: float
    new_rule_hits: list[str]
    new_tags: list[str]
    score_diff: float
    decision_changed: bool


class ReplayResponse(BaseModel):
    tenant_id: str
    events_evaluated: int
    decisions_changed: int
    results: list[ReplayResultItem]
    missing_trace_ids: list[str] = Field(default_factory=list)
    """UUID strings requested but not found for this tenant (paired replay diagnostics)."""


def _evaluate_override_rules(
    features: dict[str, Any],
    rules: list[ReplayRule],
) -> tuple[list[str], list[str], float]:
    """Run the override rule set against a feature dict.

    Returns (rule_ids, tags, score_delta) — same shape as
    ``json_rules.evaluate_json_rules`` but using the caller-supplied rules
    instead of the on-disk packs.
    """
    hits: list[str] = []
    tags: list[str] = []
    delta = 0.0
    for rule in rules:
        rid = rule.id or "anon"
        conditions = rule.when
        if not conditions:
            continue
        if all(_match_condition(features, {"field": c.field, "op": c.op, "value": c.value}) for c in conditions):
            hits.append(rid)
            tags.extend(rule.tags)
            delta += rule.score_delta
    return hits, tags, delta


def _decide(score: float, deny: float = 80.0, review: float = 50.0) -> str:
    if score >= deny:
        return "deny"
    if score >= review:
        return "review"
    return "allow"


@router.post("", response_model=ReplayResponse)
async def replay_events(
    body: ReplayRequest,
    session: AsyncSession = Depends(get_session),
):
    """Re-evaluate recent audit records with overridden rules.

    For each historical event the endpoint:
    1. Extracts the stored ``payload_snapshot`` features.
    2. Applies the caller-supplied ``rules_override`` list.
    3. Computes a new score and decision.
    4. Returns a side-by-side comparison (old vs new).
    """
    if not body.rules_override:
        raise HTTPException(
            status_code=400,
            detail="rules_override must contain at least one rule",
        )

    missing_trace_ids: list[str] = []
    if body.trace_ids:
        if len(body.trace_ids) > 200:
            raise HTTPException(status_code=400, detail="trace_ids must contain at most 200 entries")
        parsed: list[uuid_lib.UUID] = []
        for raw in body.trace_ids:
            try:
                parsed.append(uuid_lib.UUID(str(raw).strip()))
            except (ValueError, AttributeError, TypeError):
                raise HTTPException(status_code=400, detail=f"invalid trace_id: {raw!r}")
        stmt = select(AuditRecord).where(
            AuditRecord.tenant_id == body.tenant_id,
            AuditRecord.trace_id.in_(parsed),
        )
        result = await session.execute(stmt)
        found_map = {row.trace_id: row for row in result.scalars().all()}
        records = []
        for u in parsed:
            row = found_map.get(u)
            if row:
                records.append(row)
            else:
                missing_trace_ids.append(str(u))
    else:
        stmt = select(AuditRecord).where(AuditRecord.tenant_id == body.tenant_id).order_by(AuditRecord.created_at.desc()).limit(body.limit)
        result = await session.execute(stmt)
        records = list(result.scalars().all())

    if not records:
        raise HTTPException(
            status_code=404,
            detail=f"no audit records found for tenant '{body.tenant_id}'",
        )

    results: list[ReplayResultItem] = []
    decisions_changed = 0

    for rec in records:
        snapshot: dict[str, Any] = rec.payload_snapshot or {}
        features: dict[str, Any] = {
            **snapshot.get("payload", {}),
            **snapshot.get("metadata", {}),
        }

        new_hits, new_tags, score_delta = _evaluate_override_rules(features, body.rules_override)
        new_score = max(0.0, min(100.0, rec.score + score_delta))
        new_decision = _decide(new_score)
        changed = new_decision != rec.decision

        if changed:
            decisions_changed += 1

        results.append(
            ReplayResultItem(
                trace_id=str(rec.trace_id),
                entity_id=rec.entity_id,
                event_type=rec.event_type,
                original_decision=rec.decision,
                original_score=rec.score,
                original_rule_hits=rec.rule_hits or [],
                new_decision=new_decision,
                new_score=new_score,
                new_rule_hits=new_hits,
                new_tags=new_tags,
                score_diff=round(new_score - rec.score, 4),
                decision_changed=changed,
            )
        )

    return ReplayResponse(
        tenant_id=body.tenant_id,
        events_evaluated=len(results),
        decisions_changed=decisions_changed,
        results=results,
        missing_trace_ids=missing_trace_ids,
    )
