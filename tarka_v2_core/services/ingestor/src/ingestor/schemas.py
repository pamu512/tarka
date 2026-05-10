"""Pydantic API schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .manifest_schema import TransactionSchema  # noqa: F401 — public re-export for shadow_agent

CaseStatus = Literal["INVESTIGATING", "FLAGGED", "CLEARED"]
LeadWorkflowStatus = Literal["OPEN", "VERIFIED", "DISMISSED", "ESCALATED"]


class HealthResponse(BaseModel):
    ok: bool = True
    ollama_reachable: bool = False
    ollama_model: str = Field(
        default="llama3.2",
        description="Effective Ollama model (after any preferences file override).",
    )
    ollama_env_default: str = Field(
        default="llama3.2",
        description="Model from SHADOW_OLLAMA_MODEL before applying .data/preferences.json.",
    )
    ollama_using_override: bool = Field(
        default=False,
        description="True when .data/preferences.json supplies ollama_model.",
    )


class LlmPreferencesOut(BaseModel):
    """Effective model plus whether a disk override is active."""

    ollama_model: str
    env_default: str
    using_override: bool


class LlmPreferencesPatch(BaseModel):
    """Set `ollama_model` to a tag pulled in Ollama, or JSON null to clear override and use env default."""

    ollama_model: str | None  # required key; use null to revert


class OllamaModelsOut(BaseModel):
    """Tags reported by the local Ollama daemon (`/api/tags`), for UI pickers."""

    models: list[str] = Field(default_factory=list)
    error: str | None = None


class PersonaSuggestionOut(BaseModel):
    """Auto-detected lens recommendation from dataset schema (e.g. chargeback columns)."""

    persona_id: str
    display_name: str
    reason: str
    matching_columns: list[str] = Field(default_factory=list)


class PersonaListItem(BaseModel):
    """Public persona metadata for the Agent Console selector."""

    id: str
    display_name: str
    recommended_tools: list[str]
    suggested_queries: list[str]


class CaseCreate(BaseModel):
    name: str
    dataset_path: str | None = None
    status: CaseStatus = "INVESTIGATING"
    tenant_id: str | None = Field(
        default=None,
        max_length=128,
        description="Logical tenant / org id for warehouse isolation (default: default).",
    )


class CasesPurgeOut(BaseModel):
    ok: bool = True
    cases_removed: int = 0


class CasePatch(BaseModel):
    status: CaseStatus | None = None
    name: str | None = Field(default=None, max_length=256)

    @model_validator(mode="after")
    def require_touch(self):
        if self.status is None and self.name is None:
            raise ValueError("At least one of status or name is required")
        return self


class CaseShareCreate(BaseModel):
    """Grant ``viewer_case_id`` read access to this case's rows in the tenant warehouse."""

    viewer_case_id: str = Field(..., min_length=1, max_length=64)


class CaseShareOut(BaseModel):
    id: int
    owner_case_id: str
    viewer_case_id: str

    class Config:
        from_attributes = True


class CaseOut(BaseModel):
    id: str
    tenant_id: str = "default"
    name: str
    dataset_path: str | None
    duckdb_path: str | None = None
    is_active: bool
    status: CaseStatus
    created_at: datetime | None = None
    updated_at: datetime | None = None
    schema_summary: dict[str, Any] | None = None
    lead_count: int = 0
    evidence_event_count: int = 0
    script_run_count: int = 0
    last_memory_at: datetime | None = None
    persona_suggestion: PersonaSuggestionOut | None = None

    class Config:
        from_attributes = True


class LeadOut(BaseModel):
    id: str
    case_id: str
    description: str
    severity_score: float
    raw_data_ref: dict[str, Any] | None
    status: str
    created_at: datetime | None = None

    class Config:
        from_attributes = True


class AuditLogOut(BaseModel):
    id: int
    case_id: str
    action_taken: str
    code_executed: str | None
    agent_notes: str | None
    timestamp: datetime | None = None

    class Config:
        from_attributes = True


class EvidenceBoardResponse(BaseModel):
    leads: list[LeadOut]
    audit_logs: list[AuditLogOut]


class SimulateRepresentmentRequest(BaseModel):
    """Optional transaction scope for issuer-side representment simulation."""

    transaction_id: str | None = Field(
        default=None, description="Row-level manifest; omit for cohort-only review."
    )


class AtoUserRequest(BaseModel):
    user_id: str = Field(..., min_length=1)
    user_column: str | None = Field(
        default=None, description="Override auto-detected user id column name."
    )


class AtoAnalyzeRequest(BaseModel):
    """Live session telemetry vs DuckDB baseline. user_id may be omitted to infer acc_id / user_id from schema."""

    user_id: str | None = Field(
        default=None, description="Account id; omit for schema-based default (most common id)."
    )
    user_column: str | None = Field(
        default=None, description="Override auto-detected user id column name."
    )
    current_session: dict[str, Any] = Field(default_factory=dict)


class AtoKillSessionRequest(BaseModel):
    user_id: str = Field(..., min_length=1)
    session_id: str | None = None
    reason: str | None = Field(default=None, max_length=2000)


class BotBulkSuspendRequest(BaseModel):
    """Audit stub: bulk flag / suspend many accounts from a bot cluster."""

    account_ids: list[str] = Field(..., min_length=1, max_length=50000)
    reason: str = Field(default="BOT_CLUSTER_SYNC_BURST", max_length=2000)
    cluster_id: str | None = Field(default=None, max_length=512)


class LeadStatusPatch(BaseModel):
    status: LeadWorkflowStatus


class ActivitySeriesPayload(BaseModel):
    values: list[float]
    threshold: float


class ActivityBulkRequest(BaseModel):
    case_ids: list[str] = Field(default_factory=list)


class ActivityBulkResponse(BaseModel):
    activities: dict[str, ActivitySeriesPayload]


class AgentQueryRequest(BaseModel):
    case_id: str
    sql: str = Field(
        ..., min_length=1, description="SELECT or WITH query against the case DuckDB dataset table."
    )


class AgentQueryResponse(BaseModel):
    columns: list[str]
    rows: list[list[Any]]
    row_count: int


class ChatMessage(BaseModel):
    role: Literal["system", "user", "assistant"]
    content: str


class ChatRequest(BaseModel):
    messages: list[ChatMessage]
    case_id: str | None = None
    persona_id: str | None = Field(
        default=None,
        description="Investigative lens id (e.g. chargeback_specialist). Defaults to general.",
    )
    thread_id: str | None = Field(
        default=None,
        description="Stable id for LangGraph checkpointing across turns (rotate on new chat / case / persona).",
    )
    thread_reset: bool = Field(
        default=False,
        description="When true, drop compiled LangGraph cache for this persona so tools/prompts reload; "
        "client should send after persona switch.",
    )


class ChatResponse(BaseModel):
    messages: list[ChatMessage]
    debug: dict[str, Any] | None = None
    persona_id: str = "general"
    persona_suggestion: PersonaSuggestionOut | None = None


class WarehouseOverlapOut(BaseModel):
    """Cross-case entity hit payload (Global DuckDB warehouse)."""

    model_config = ConfigDict(extra="ignore")

    ok: bool = True
    entity_id: str = ""
    entity_type: str = ""
    distinct_case_count: int = 0
    other_case_count_excluding_active: int | None = None
    other_cases: list[dict[str, Any]] = Field(default_factory=list)
    recidivist_fraudster: bool = False
    priority: str = "Normal"
    note: str | None = None
    global_hits: bool | None = None
    kind: str | None = None


class CodeReviewRequest(BaseModel):
    script: str
    language: Literal["python", "r"]
    case_id: str | None = None


class CodeReviewResponse(BaseModel):
    original: str
    suggested: str
    notes: str


class ExecuteRequest(BaseModel):
    language: Literal["python", "r"]
    code: str
    case_id: str | None = None
    timeout_sec: int = Field(default=120, ge=5, le=600)


class ExecuteResponse(BaseModel):
    stdout: str
    stderr: str
    exit_code: int
    plots_base64: list[str] = Field(default_factory=list)
    violations: list[str] | None = None


class ScaffoldRequest(BaseModel):
    language: Literal["python", "r"]
    intent: str
    case_id: str | None = None
    columns: list[dict[str, str]] | None = None


class ScaffoldResponse(BaseModel):
    code: str
    explanation: str


class OptimizeThresholdsRequest(BaseModel):
    case_id: str | None = None
    dataset_path: str | None = None
    model: Literal["isolation_forest", "random_forest"] = "isolation_forest"
    target_column: str | None = None
    optimization_objective: str | None = Field(
        default=None,
        description="e.g. youden_j, min_fpr_at_recall_0.8",
    )


class OptimizeThresholdsResponse(BaseModel):
    thresholds: dict[str, Any]
    optimization_manifest: dict[str, Any]
    metrics_at_threshold: dict[str, Any]
    optimization_objective: str


class WorkbenchPinItem(BaseModel):
    """Pinned forensic card (matches frontend PinnedForensicPayload)."""

    id: str
    title: str
    subtitle: str = ""
    payload: dict[str, Any] = Field(default_factory=dict)
    pinned_at: int = Field(default=0, alias="pinnedAt")

    model_config = ConfigDict(populate_by_name=True)


class WorkbenchPinsPut(BaseModel):
    pins: list[WorkbenchPinItem] = Field(default_factory=list, max_length=24)


class WorkbenchPinsOut(BaseModel):
    pins: list[dict[str, Any]]
