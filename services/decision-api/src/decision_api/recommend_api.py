from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from decision_api.db import get_session
from decision_api.models import AuditRecord
from decision_api.rule_recommender import (
    analyze_features,
    generate_recommendations,
)

"""Rule recommendation API — AI-powered rule suggestion from historical data."""

log = logging.getLogger(__name__)
router = APIRouter(prefix="/v1/recommendations", tags=["recommendations"])
_SAFE_PACK_RE = re.compile(r"^[a-zA-Z0-9_-]{1,120}\.json$")


def _resolve_existing_pack(rules_dir: Path, pack_name: str) -> Path:
    if not _SAFE_PACK_RE.fullmatch(pack_name):
        raise HTTPException(400, "invalid target_pack")
    candidates = {p.name: p for p in rules_dir.glob("*.json") if p.is_file()}
    path = candidates.get(pack_name)
    if not path:
        raise HTTPException(404, f"Pack '{pack_name}' not found")
    return path


class RecommendRequest(BaseModel):
    tenant_id: str
    limit: int = Field(default=1000, ge=100, le=10000)
    max_rules: int = Field(default=10, ge=1, le=50)
    min_confidence: float = Field(default=0.3, ge=0.0, le=1.0)


@router.post("/analyze")
async def analyze(
    body: RecommendRequest,
    session: AsyncSession = Depends(get_session),
):
    """Analyze historical decisions and return feature insights + rule recommendations."""
    stmt = select(AuditRecord).where(AuditRecord.tenant_id == body.tenant_id).order_by(AuditRecord.created_at.desc()).limit(body.limit)
    result = await session.execute(stmt)
    records_raw = list(result.scalars().all())

    if len(records_raw) < 20:
        raise HTTPException(400, f"Need at least 20 records for analysis, found {len(records_raw)}")

    records = [
        {
            "decision": r.decision,
            "score": r.score,
            "payload_snapshot": r.payload_snapshot,
            "rule_hits": r.rule_hits,
        }
        for r in records_raw
    ]

    insights = analyze_features(records)
    recommendations = generate_recommendations(
        records,
        max_rules=body.max_rules,
        min_confidence=body.min_confidence,
    )

    total = len(records)
    fraud_count = sum(1 for r in records if r["decision"] in ("deny", "review"))

    return {
        "tenant_id": body.tenant_id,
        "records_analyzed": total,
        "fraud_rate": round(fraud_count / max(total, 1), 4),
        "insights": [i.model_dump() for i in insights[:20]],
        "recommendations": [r.model_dump() for r in recommendations],
    }


class ApplyRecommendationRequest(BaseModel):
    target_pack: str
    rule: dict


@router.post("/apply")
async def apply_recommendation(body: ApplyRecommendationRequest):
    """Apply a recommended rule directly to a rule pack file."""
    from decision_api.config import settings
    from decision_api.json_rules import load_rules

    rules_dir = Path(settings.rules_path)
    pack_path = _resolve_existing_pack(rules_dir, body.target_pack)

    pack = json.loads(pack_path.read_text(encoding="utf-8"))
    pack.setdefault("rules", []).append(body.rule)
    pack_path.write_text(json.dumps(pack, indent=2), encoding="utf-8")
    load_rules()
    return {"ok": True, "pack": body.target_pack, "rule_id": body.rule.get("id", "unknown")}


@router.post("/preview")
async def preview_recommendation(
    body: dict[str, Any],
    session: AsyncSession = Depends(get_session),
):
    """Preview impact of a rule against recent audit records."""
    tenant_id = body.get("tenant_id")
    rule = body.get("rule")
    if not tenant_id or not rule:
        raise HTTPException(400, "tenant_id and rule are required")

    from datetime import datetime, timedelta, timezone

    from decision_api.json_rules import evaluate_adhoc_packs_json

    cutoff = datetime.now(timezone.utc) - timedelta(days=30)
    stmt = (
        select(AuditRecord).where(AuditRecord.tenant_id == tenant_id).where(AuditRecord.created_at >= cutoff).order_by(AuditRecord.created_at.desc()).limit(500)
    )
    result = await session.execute(stmt)
    records = list(result.scalars().all())

    pack = {"rules": [rule], "tag_rules": [], "version": 1, "mode": "active", "_source_file": "preview.json"}
    affected = 0
    would_change = 0

    for rec in records:
        snapshot = rec.payload_snapshot or {}
        features = {**snapshot.get("payload", {}), **snapshot.get("metadata", {})}
        hits, tags, delta, _pf = evaluate_adhoc_packs_json(
            [pack],
            features,
            [],
            evaluation_mode="simulation",
            record_telemetry=False,
        )
        if hits:
            affected += 1
            new_score = max(0.0, min(100.0, rec.score + delta))
            if new_score >= 80:
                new_decision = "deny"
            elif new_score >= 50:
                new_decision = "review"
            else:
                new_decision = "allow"
            if new_decision != rec.decision:
                would_change += 1

    return {
        "records_tested": len(records),
        "affected": affected,
        "decisions_would_change": would_change,
        "impact_rate": round(affected / max(len(records), 1) * 100, 1),
    }


@router.post("/generate")
async def generate_recommendations_endpoint(
    body: RecommendRequest,
    session: AsyncSession = Depends(get_session),
):
    """Legacy endpoint — delegates to /analyze."""
    from datetime import datetime, timedelta, timezone

    cutoff = datetime.now(timezone.utc) - timedelta(days=30)
    stmt = (
        select(AuditRecord)
        .where(AuditRecord.tenant_id == body.tenant_id)
        .where(AuditRecord.created_at >= cutoff)
        .order_by(AuditRecord.created_at.desc())
        .limit(body.limit)
    )
    result = await session.execute(stmt)
    records_raw = list(result.scalars().all())

    if not records_raw:
        raise HTTPException(404, f"No audit records found for tenant '{body.tenant_id}'")

    from decision_api.rule_recommender import RuleRecommender

    observations = []
    for rec in records_raw:
        snapshot = rec.payload_snapshot or {}
        features = {**snapshot.get("payload", {}), **snapshot.get("metadata", {})}
        observations.append({"decision": rec.decision, "score": rec.score, "features": features})

    recommender = RuleRecommender()
    recommender.ingest(observations)
    recs = recommender.analyze(min_support=5, min_precision=0.3)

    return {
        "tenant_id": body.tenant_id,
        "records_analyzed": len(records_raw),
        "recommendations": recs,
    }
