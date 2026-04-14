from enum import Enum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class EventType(str, Enum):
    login = "login"
    payment = "payment"
    signup = "signup"
    device = "device"
    session = "session"
    custom = "custom"


class DeviceContextIn(BaseModel):
    device_id: str
    platform: str = "web"
    signals: dict[str, Any] = Field(default_factory=dict)
    attestation: dict[str, Any] | None = None
    behavior: dict[str, Any] | None = None


class EvaluateRequest(BaseModel):
    tenant_id: str
    event_type: EventType
    entity_id: str
    session_id: str | None = None
    region: str = "global"
    payload: dict[str, Any] = Field(default_factory=dict)
    device_context: DeviceContextIn | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    challenge_policy_id: str | None = Field(
        default=None,
        description="Optional challenge/escalation template id (JSON in rules/challenge_policies/)",
    )


class InferenceContext(BaseModel):
    schema_version: str = "2"
    integrity_confidence: float = 0.0
    tamper_risk: float = 0.0
    network_trust: float = 0.0
    replay_risk: float = 0.0
    geo_consistency_risk: float = 0.0
    top_signals: list[str] = Field(default_factory=list)
    confidence_tier: str = "medium"
    driver_reasons: list[str] = Field(default_factory=list)
    colocation_risk: float = 0.0
    impossible_travel_risk: float = 0.0
    velocity_events_5m: int = 0
    velocity_events_1h: int = 0
    velocity_events_24h: int = 0
    ml_top_factors: list[dict[str, Any]] = Field(default_factory=list)
    ml_summary: str | None = None
    ml_model: str | None = None


class EvaluateResponse(BaseModel):
    trace_id: UUID
    decision: str
    score: float
    tags: list[str]
    rule_hits: list[str] = Field(default_factory=list)
    reasons: list[str] = Field(default_factory=list)
    ml_score: float | None = None
    inference_context: InferenceContext
    recommended_action: str | None = None
    challenge_policy_id: str | None = Field(
        default=None,
        description="Resolved challenge template id (may differ from request if default applied)",
    )
    challenge_metadata: dict[str, Any] | None = Field(
        default=None,
        description="Matched rule id, escalation ladder, etc.",
    )
