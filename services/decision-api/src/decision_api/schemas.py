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
        normalized = normalize_attestation_object(
            self.attestation, platform=self.platform
        )
        if normalized is None:
            object.__setattr__(self, "attestation", None)
        else:
            object.__setattr__(self, "attestation", normalized)
        return self


class AgentClientIn(BaseModel):
    """Registered client / capability manifest for agent-mediated evaluate calls."""

    client_type: str | None = Field(
        default=None,
        description="e.g. mcp, copilot_plugin, sdk, browser_extension, unknown",
    )
    oauth_client_id: str | None = None
    mcp_server_ids: list[str] = Field(default_factory=list)
    manifest_hash: str | None = Field(
        default=None, description="Hash of capability manifest / config"
    )
    tool_allowlist_hash: str | None = None
    sdk_version: str | None = None


class HumanControlIn(BaseModel):
    """Human-in-the-loop and maker–checker signals for sensitive agent actions."""

    hitl_required_for_event: bool | None = None
    human_approval_received: bool | None = None
    approver_entity_id: str | None = None
    maker_checker_satisfied: bool | None = None


class OrchestrationIn(BaseModel):
    """Tool loop telemetry (hashes preferred over raw prompts)."""

    turn_id: str | None = None
    tool_names_ordered: list[str] = Field(default_factory=list)
    tool_sequence_digest: str | None = None
    tool_depth: int | None = None
    tool_retry_count: int | None = None
    plan_digest: str | None = None
    untrusted_content_sources: list[str] = Field(default_factory=list)


class IntegrityIn(BaseModel):
    """Heuristic flags from gateways or copilot; weak learners for rules/ML."""

    prompt_injection_heuristic_flag: bool | None = None
    cross_channel_mismatch_flag: bool | None = None
    policy_denial_count_this_session: int | None = None


class AgentContextIn(BaseModel):
    """Optional envelope for LLM agent / MCP session context on synchronous evaluate."""

    agent_runtime_id: str | None = Field(
        default=None,
        description="Stable-ish id for this installed agent runtime (rotates on reinstall)",
    )
    agent_session_id: str | None = Field(
        default=None,
        description="Ephemeral conversation or MCP session id",
    )
    agent_client: AgentClientIn | None = None
    human_control: HumanControlIn | None = None
    orchestration: OrchestrationIn | None = None
    integrity: IntegrityIn | None = None


class EvaluateRequest(BaseModel):
    tenant_id: str
    event_type: EventType
    entity_id: str
    session_id: str | None = None
    region: str = "global"
    payload: dict[str, Any] = Field(default_factory=dict)
    device_context: DeviceContextIn | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    agent_context: AgentContextIn | None = Field(
        default=None,
        description="Optional agent/MCP session context; merged into rule features when present",
    )
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
        default_factory=lambda: {
            "calibration": "heuristic",
            "counter": "heuristic",
            "location": "heuristic",
        }
    )
    graph_risk_score: float = 0.0
    graph_risk_reasons: list[str] = Field(default_factory=list)
    external_signal_score: float = 0.0
    external_signal_providers: list[str] = Field(default_factory=list)
    policy_experiment_id: str | None = None
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
    graph_decision_explanation: dict[str, Any] | None = Field(
        default=None,
        description="When graph risk ran: tarka.graph_decision_explanation/v1 factor→evidence mapping for case/analyst UI",
    )
