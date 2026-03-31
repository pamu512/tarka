from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class CreateCaseRequest(BaseModel):
    tenant_id: str
    title: str
    entity_id: str
    trace_id: str
    priority: str = "medium"


class CaseOut(BaseModel):
    id: UUID
    tenant_id: str
    title: str
    status: str
    entity_id: str
    trace_id: str
    priority: str = "medium"
    assigned_team: str | None = None
    labels: list[str]
    created_at: datetime | None
    updated_at: datetime | None

    model_config = {"from_attributes": True}


class CommentIn(BaseModel):
    author: str
    body: str


class LabelsIn(BaseModel):
    labels: list[str]


class CreateDisputeRequest(BaseModel):
    tenant_id: str
    entity_id: str
    trace_id: str
    dispute_type: str = "chargeback"
    reason_code: str = ""
    amount: float = 0.0
    currency: str = "USD"
    merchant_id: str | None = None
    card_network: str | None = None
    case_id: str | None = None


class UpdateDisputeRequest(BaseModel):
    status: str | None = None
    outcome: str | None = None
    resolution_notes: str | None = None


class DisputeOut(BaseModel):
    id: UUID
    case_id: UUID | None
    tenant_id: str
    entity_id: str
    trace_id: str
    dispute_type: str
    status: str
    reason_code: str
    amount: float
    currency: str
    merchant_id: str | None
    card_network: str | None
    original_decision: str | None
    original_score: float | None
    original_rule_hits: list[str]
    original_ml_score: float | None
    outcome: str | None
    resolution_notes: str | None
    filed_at: datetime | None
    resolved_at: datetime | None
    created_at: datetime | None
    updated_at: datetime | None

    model_config = {"from_attributes": True}
