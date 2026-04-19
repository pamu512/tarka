from __future__ import annotations

from enum import Enum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

from decision_api.attestation_taxonomy import normalize_attestation_object


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

    @model_validator(mode="after")
    def _normalize_attestation(self) -> DeviceContextIn:
        if self.attestation is None:
            return self
        normalized = normalize_attestation_object(self.attestation, platform=self.platform)
        if normalized is None:
            object.__setattr__(self, "attestation", None)
        else:
            object.__setattr__(self, "attestation", normalized)
        return self


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


class DriverExplainEntry(BaseModel):
    reason: str
    category: str = "other"
    label: str = ""


class InferenceContext(BaseModel):
    schema_version: str = "3"
    calibration_profile: str = "default"
    expected_calibration_version: int = 1
    confidence_tier_label: str = ""
    driver_explain: list[DriverExplainEntry] = Field(default_factory=list)
    integrity_confidence: float = 0.0
    tamper_risk: float = 0.0
    network_trust: float = 0.0
    replay_risk: float = 0.0
    geo_consistency_risk: float = 0.0
    top_signals: list[str] = Field(default_factory=list)
    confidence_tier: str = "medium"
    driver_reasons: list[str] = Field(default_factory=list)
    colocation_risk: float = 0.0
    copresence_risk: float = 0.0
    impossible_travel_risk: float = 0.0
    velocity_events_5m: int = 0
    velocity_events_1h: int = 0
    velocity_events_24h: int = 0
    calibration_profile_version: int = 1
    location_confidence: float = 0.0
    confidence_sources: dict[str, str] = Field(
        default_factory=lambda: {"calibration": "heuristic", "counter": "heuristic", "location": "heuristic"}
    )
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
    fallback_reason: str | None = Field(
        default=None,
        description="Set when evaluate used rules-only or degraded dependencies (circuit/tenant flags); mirrors audit payload_snapshot.fallback_reason",
    )
