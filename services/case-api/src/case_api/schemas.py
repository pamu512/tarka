from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class CreateCaseRequest(BaseModel):
    tenant_id: str
    title: str
    entity_id: str
    trace_id: str
    priority: str = "medium"
    playbook_id: str | None = Field(
        default=None,
        description=(
            "Optional playbook slug (GET /v1/cases/playbooks) or investigation-template UUID "
            "(GET /v1/investigation-templates), applied immediately after create."
        ),
    )


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
    default_owner: str | None = None
    sla_hours_override: int | None = None
    applied_template_id: UUID | None = None
    created_at: datetime | None
    updated_at: datetime | None

    model_config = {"from_attributes": True}


class InvestigationTemplateApplyConfig(BaseModel):
    """Payload applied to a case when a template (or playbook extension) runs."""

    status: str | None = None
    priority: str | None = None
    assigned_team: str | None = None
    labels: list[str] | None = None
    comment: str | None = None
    default_owner: str | None = None
    sla_hours: int | None = Field(default=None, ge=1, le=8760)
    escalation_team: str | None = None


class InvestigationTemplateOut(BaseModel):
    id: UUID
    tenant_id: str
    slug: str
    name: str
    apply_config: dict[str, Any]
    created_at: datetime | None
    updated_at: datetime | None

    model_config = {"from_attributes": True}


class CreateInvestigationTemplateRequest(BaseModel):
    tenant_id: str
    slug: str = Field(min_length=2, max_length=128, pattern=r"^[a-z0-9][a-z0-9_-]*$")
    name: str = Field(min_length=1, max_length=256)
    apply: InvestigationTemplateApplyConfig


class PatchInvestigationTemplateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=256)
    apply: InvestigationTemplateApplyConfig | None = None


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
    provider_response_deadline_at: datetime | None = None
    provider_response_deadline_hours: int | None = Field(
        default=None,
        ge=1,
        le=8760,
        description="Alternative to absolute deadline: hours from filing for provider/webhook response window.",
    )


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
    provider_response_deadline_at: datetime | None = None
    external_reprocess_count: int = 0
    last_external_reprocess_at: datetime | None = None
    created_at: datetime | None
    updated_at: datetime | None

    model_config = {"from_attributes": True}


class LabelDraftRowIn(BaseModel):
    trace_id: str | None = None
    entity_id: str | None = None
    y_label: str
    source: str = "analyst"
    notes: str | None = None


class LabelDraftBatchIn(BaseModel):
    analyst_id: str
    rows: list[LabelDraftRowIn] = Field(default_factory=list, max_length=50)
    clear_existing: bool = False


class LabelDraftOut(BaseModel):
    id: UUID
    tenant_id: str
    analyst_id: str
    trace_id: str | None
    entity_id: str | None
    y_label: str
    source: str
    notes: str | None
    created_at: datetime | None
    updated_at: datetime | None

    model_config = {"from_attributes": True}
