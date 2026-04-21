from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from decision_api.config import settings
from decision_api.consortium import hash_entity_id
from decision_api.redis_store import redis_tags

router = APIRouter(prefix="/v1/consortium", tags=["consortium"])


class ConsortiumShareRequest(BaseModel):
    tenant_id: str = Field(min_length=1, max_length=128)
    entity_id: str = Field(min_length=1, max_length=512)
    signal_type: str = Field(min_length=1, max_length=64)
    severity: float = Field(default=1.0, ge=0.0, le=5.0)
    ttl_days: int = Field(default=30, ge=1, le=365)
    consortium_id: str | None = Field(default=None, max_length=128)


class ConsortiumTrustRequest(BaseModel):
    tenant_id: str = Field(min_length=1, max_length=128)
    trust_score: float = Field(ge=0.1, le=2.0)
    consortium_id: str | None = Field(default=None, max_length=128)


class ConsortiumFeedbackRequest(BaseModel):
    tenant_id: str = Field(min_length=1, max_length=128)
    entity_id: str = Field(min_length=1, max_length=512)
    outcome: str = Field(pattern="^(false_positive|confirmed_fraud)$")
    ttl_days: int = Field(default=30, ge=1, le=365)
    consortium_id: str | None = Field(default=None, max_length=128)


@router.post("/share")
async def share_signal(body: ConsortiumShareRequest) -> dict[str, Any]:
    if not settings.consortium_enabled:
        raise HTTPException(status_code=403, detail="consortium disabled")
    consortium_id = (body.consortium_id or settings.consortium_id).strip()
    signal_hash = hash_entity_id(
        settings.consortium_secret,
        body.tenant_id,
        body.entity_id,
        hash_scope=settings.consortium_hash_scope,
    )
    data = await redis_tags.record_consortium_signal(
        consortium_id=consortium_id,
        signal_hash=signal_hash,
        signal_type=body.signal_type.strip().lower(),
        reporter_tenant=body.tenant_id.strip(),
        severity=body.severity,
        ttl_days=body.ttl_days,
    )
    return {"signal_hash": signal_hash, "consortium": data}


@router.get("/check/{tenant_id}/{entity_id}")
async def check_signal(tenant_id: str, entity_id: str, consortium_id: str | None = None) -> dict[str, Any]:
    if not settings.consortium_enabled:
        return {"enabled": False, "consortium": {}}
    cid = (consortium_id or settings.consortium_id).strip()
    signal_hash = hash_entity_id(
        settings.consortium_secret,
        tenant_id,
        entity_id,
        hash_scope=settings.consortium_hash_scope,
    )
    data = await redis_tags.check_consortium_signal(cid, signal_hash)
    return {"enabled": True, "signal_hash": signal_hash, "consortium": data}


@router.post("/trust")
async def set_tenant_trust(body: ConsortiumTrustRequest) -> dict[str, Any]:
    if not settings.consortium_enabled:
        raise HTTPException(status_code=403, detail="consortium disabled")
    cid = (body.consortium_id or settings.consortium_id).strip()
    data = await redis_tags.set_consortium_tenant_trust(cid, body.tenant_id.strip(), body.trust_score)
    return {"ok": True, "trust": data}


@router.post("/feedback")
async def add_feedback(body: ConsortiumFeedbackRequest) -> dict[str, Any]:
    if not settings.consortium_enabled:
        raise HTTPException(status_code=403, detail="consortium disabled")
    cid = (body.consortium_id or settings.consortium_id).strip()
    signal_hash = hash_entity_id(
        settings.consortium_secret,
        body.tenant_id,
        body.entity_id,
        hash_scope=settings.consortium_hash_scope,
    )
    data = await redis_tags.add_consortium_feedback(
        consortium_id=cid,
        signal_hash=signal_hash,
        outcome=body.outcome,
        ttl_days=body.ttl_days,
    )
    return {"ok": True, "signal_hash": signal_hash, "consortium": data}
