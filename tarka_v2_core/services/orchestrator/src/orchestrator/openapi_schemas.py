"""OpenAPI response and error models for ReDoc / OpenAPI generation."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ValidationErrorItem(BaseModel):
    """One field-level validation failure."""

    loc: list[str | int] = Field(
        ...,
        description="Location of the invalid value (e.g. `body`, field name, nested keys).",
        examples=[["body", "amount"]],
    )
    msg: str = Field(..., description="Explanation suitable for API consumers.")
    type: str = Field(..., description="Machine-readable error type identifier.")


class HTTPValidationError422(BaseModel):
    """Returned when the JSON body does not satisfy the published request schema."""

    detail: list[ValidationErrorItem]


class ChargebackIngestRequest(BaseModel):
    """``POST /v1/ingest/chargeback`` — specialized dispute envelope tied to an original payment."""

    model_config = ConfigDict(extra="forbid")

    original_entity_id: UUID = Field(
        ...,
        description="UUID of the original settled transaction (``entity_id`` from the payment ingest).",
    )
    amount: float = Field(
        ...,
        gt=0,
        description="Chargeback amount in the same currency convention as standard ingests.",
    )
    session_id: str | None = Field(
        None,
        max_length=256,
        description=(
            "Checkout / device session id for the original payment. When omitted, the orchestrator "
            "scans recent ``audit_logs`` JSON for a ``session_id`` associated with ``original_entity_id``."
        ),
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Optional metadata merged into the dispute ``TransactionSchema`` (chargeback fields win on keys).",
    )
    country: str | None = Field(
        default=None,
        max_length=8,
        description="Optional ISO-like country code mirrored on the dispute envelope.",
    )


class IngestResponse(BaseModel):
    """Successful `/v1/ingest` response: policy outcome plus optional secondary analysis."""

    model_config = ConfigDict(extra="allow")

    rule_engine: dict[str, Any] = Field(
        ...,
        description=(
            "Opaque policy evaluation payload returned to callers "
            "(for example actions and identifiers produced by the rules tier)."
        ),
    )
    transaction_id: str = Field(
        ...,
        description="UUID string matching the submitted transaction `entity_id`.",
    )
    shadow_agent: dict[str, Any] | None = Field(
        None,
        description=(
            "Structured fraud-analysis output when a secondary review step completed successfully."
        ),
    )
    orchestrator_fallback_decision: str | None = Field(
        None,
        description="When secondary review was requested but did not return a body, may be `FLAG`.",
    )
    orchestrator_fallback_reason: str | None = Field(
        None,
        description="Machine-readable reason for fallback (timeout, transport failure, etc.).",
    )
    orchestrator_shadow_deadline_seconds: float | None = Field(
        None,
        description="Read deadline used for secondary review when a timeout fallback occurred.",
    )


class ServiceProbe(BaseModel):
    """Single component row in the aggregate health matrix."""

    component: str
    status: str
    latency_ms: float | None = None
    detail: str


class HealthFullResponse(BaseModel):
    """Aggregate readiness snapshot across orchestrator and configured dependencies."""

    generated_at: str = Field(
        ...,
        description="UTC timestamp (ISO 8601) when this snapshot was produced.",
    )
    services: list[ServiceProbe] = Field(
        ...,
        description="Per-component status, round-trip latency where applicable, and short detail text.",
    )


class DemoResultRow(BaseModel):
    """One simulated transaction row for UI demonstrations."""

    pattern_index: int
    total: int
    transaction_id: str
    amount: float
    currency: str
    channel: str
    shadow_verdict: str
    integrity_confidence: float
    simulated_at: str


class DemoSimulateResponse(BaseModel):
    """Fixed-size batch of simulated results for attack-pattern visualization."""

    total: int = Field(..., description="Length of the `results` array.")
    results: list[DemoResultRow]


class KnowledgeMiniGraph(BaseModel):
    """Tiny graph sketch for UI (nodes carry layout hints; edges are undirected for display)."""

    nodes: list[dict[str, Any]] = Field(default_factory=list)
    edges: list[dict[str, Any]] = Field(default_factory=list)


class KnowledgeDropResolution(BaseModel):
    """Per-ID graph linkage + lifecycle snapshot for the Knowledge Drop Zone."""

    detected_id: str = Field(..., description="Token extracted from the uploaded document.")
    id_kind: str = Field(
        ...,
        description=(
            "Coarse classifier: ``uuid``, ``order``, ``passport``, ``txn``, ``customer`` (``cust_*``), "
            "``token``, or ``unknown``."
        ),
    )
    found_in_graph: bool = Field(
        ...,
        description="Whether the token matched a Neo4j/Janus graph pattern (transaction, order, passport, or user).",
    )
    match_kind: str | None = Field(
        default=None,
        description="Primary graph match channel (e.g. ``transaction``, ``order``, ``passport+user``).",
    )
    graph_backend: str | None = Field(
        default=None,
        description="Graph driver used for the probe (``neo4j``, ``none``, ``error``, …).",
    )
    linked_user_ids: list[str] = Field(
        default_factory=list,
        description="Distinct ``User.user_id`` values tied to this token in the graph.",
    )
    active_investigation_count: int = Field(
        ...,
        description="Lifecycle cases in OPEN / UNDER_REVIEW / PENDING_ACTION for related transaction UUIDs.",
    )
    pending_action_conflict: bool = Field(
        ...,
        description="True when any related lifecycle case is currently ``PENDING_ACTION``.",
    )
    pending_action_case_ids: list[str] = Field(
        default_factory=list,
        description="Lifecycle ``case_id`` values in ``PENDING_ACTION`` for related entities.",
    )
    mini_graph: KnowledgeMiniGraph = Field(
        default_factory=KnowledgeMiniGraph,
        description="Structured hint for rendering a micro graph in the analyst UI.",
    )
    two_hop_network: dict[str, Any] | None = Field(
        default=None,
        description="JanusGraph/Neo4j 2-hop neighborhood when the token anchors a ``User.user_id``.",
    )
    duck_cluster_velocity: dict[str, Any] | None = Field(
        default=None,
        description="DuckDB spend + 2h spike metrics for the cluster (``v_analytics_transactions``, 30d window).",
    )


class InvestigationPrimeResponse(BaseModel):
    """Result of parsing an analyst upload for cross-reference priming."""

    filename: str = Field(..., description="Sanitized original upload name.")
    detected_ids: list[str] = Field(
        ...,
        description="Unique order-like, transaction-prefixed, or UUID tokens found in the text.",
    )
    prime_prompt: str = Field(
        ...,
        description=(
            "Pre-written Shadow AI prompt when at least one ID was detected; empty string otherwise."
        ),
    )
    knowledge: list[KnowledgeDropResolution] = Field(
        default_factory=list,
        description=(
            "Graph + lifecycle enrichment for each detected ID (empty when audit DB is unavailable)."
        ),
    )
    cluster_analysis: dict[str, Any] | None = Field(
        default=None,
        description=(
            "When ``SHADOW_AGENT_URL`` is configured, structured ``POST /v1/analyze`` output using graph "
            "topology + Duck velocity in ``graph_context`` (``ai_reasoning`` should include **Cluster Analysis**)."
        ),
    )


class RuleShadowTestRequest(BaseModel):
    """Hypothetical rule predicate + outcome for offline replay against a recent transaction cohort."""

    root_node: dict[str, Any] = Field(
        ...,
        description="JSON ``LogicalNode`` (``ConditionNode``, ``AndNode``, or ``OrNode``) from the builder.",
    )
    action: str = Field(
        ...,
        description="Wire outcome when the predicate matches: ``BLOCK``, ``FLAG``, ``SHADOW_REVIEW``, or ``ALLOW``.",
    )


class RuleShadowTestResponse(BaseModel):
    """Results of replaying one rule against up to 1,000 historical (or synthetic fallback) transactions."""

    sample_size: int = Field(..., description="Number of transactions evaluated.")
    matched_count: int = Field(..., description="Count where the predicate evaluated to true.")
    match_rate: float = Field(..., description="``matched_count / sample_size``.")
    would_block_pct: float = Field(
        ...,
        description="Percentage of the cohort that would have received ``BLOCK`` when ``action`` is ``BLOCK``.",
    )
    would_flag_count: int = Field(
        ...,
        description="Count that would have been ``FLAG`` / ``SHADOW_REVIEW`` for matching non-``BLOCK`` actions.",
    )
    summary_line: str = Field(
        ...,
        description=(
            'Human-readable summary, e.g. "This rule would have blocked 12.0% of previous traffic '
            'and flagged 0 transactions."'
        ),
    )
    warning: str | None = Field(
        default=None,
        description="Populated when the match rate is extremely high (default threshold 98%).",
    )


class AnalyticsVelocityRow(BaseModel):
    """One ``(minute, country)`` bucket from the velocity aggregation."""

    minute_bucket: str = Field(
        ...,
        description="UTC minute start (ISO 8601) from ``date_trunc('minute', ts)``.",
    )
    country: str = Field(..., description="ISO-like country code from seed transactions.")
    txn_count: int = Field(..., description="Number of transactions in this minute and country.")


class AnalyticsTransactionsSnapshot(BaseModel):
    """``GET /v1/analytics/transactions``: rows from ``v_analytics_transactions`` (seed + ingested)."""

    rows: list[dict[str, Any]] = Field(
        ...,
        description="Newest-first rows from the unified analytical view (JSON-serializable values).",
    )
    next_cursor: str | None = Field(
        None,
        description="Opaque keyset cursor — pass as ``cursor`` on the next request until null.",
    )
    query_ms: float | None = Field(
        None,
        description="Wall-clock time for the analytical fetch in this worker (milliseconds).",
    )
    backend: str | None = Field(
        None,
        description="Analytics plane label (e.g. ``duckdb``, ``clickhouse``).",
    )


class AnalyticsVelocityResponse(BaseModel):
    """``GET /v1/analytics/velocity``: transactions per minute grouped by country."""

    rows: list[AnalyticsVelocityRow] = Field(
        ...,
        description="Ordered minute buckets with descending volume within each minute.",
    )
    query_ms: float = Field(
        ...,
        description="Wall-clock time for the DuckDB aggregation in this worker (milliseconds).",
    )


class BadGateway502(BaseModel):
    """Upstream dependency returned an HTTP error or violated the expected contract."""

    detail: dict[str, Any] = Field(
        ...,
        description=(
            "Structured diagnostic payload including error class, upstream HTTP status, "
            "and a truncated response preview."
        ),
    )


class ServiceUnavailable503(BaseModel):
    """Gateway could not reach an upstream dependency or complete configuration checks."""

    detail: str | dict[str, Any] = Field(
        ...,
        description="Plain string or structured object describing the failure.",
    )


class EntityProfileResponse(BaseModel):
    """``GET /v1/marketplace/users/{user_id}/entity-profile`` — unified Entity Explorer (Prompt 84)."""

    model_config = ConfigDict(extra="forbid")

    user_id: str = Field(..., description="Marketplace ``user_id`` anchor for the profile.")
    generated_at: str = Field(..., description="UTC ISO timestamp when this snapshot was assembled.")
    data_sources: dict[str, Any] = Field(
        ...,
        description=(
            "Booleans / backend labels indicating which tiers contributed (Postgres lifecycle, "
            "JanusGraph/Neo4j topology, DuckDB analytics, live Shadow ``/v1/analyze``)."
        ),
    )
    lifecycle_case: dict[str, Any] | None = Field(
        None,
        description="Latest ``lifecycle_cases`` row keyed by ``user_link_key``, or null when none.",
    )
    graph_fragment: dict[str, Any] = Field(
        default_factory=dict,
        description="Raw ``two_hop_neighbor_network`` payload from the configured graph backend.",
    )
    graph_viz: dict[str, Any] = Field(
        default_factory=dict,
        description="UI-friendly ``nodes`` / ``links`` projection for a neighborhood sketch.",
    )
    duckdb_metrics: dict[str, Any] = Field(
        default_factory=dict,
        description="Spend, listing count, and promo success rate from DuckDB ``v_analytics_transactions``.",
    )
    shadow_executive_summary: dict[str, Any] = Field(
        default_factory=dict,
        description="Shadow ``ai_reasoning`` (and scores) when live analyze succeeds; otherwise error stubs.",
    )


class CaseStatusUpdateRequest(BaseModel):
    """``PUT /v1/cases/{case_id}/status`` — body (Prompt 112)."""

    model_config = ConfigDict(extra="forbid")

    status: str = Field(
        ...,
        description="Target lifecycle status (``OPEN``, ``UNDER_REVIEW``, ``PENDING_ACTION``, …).",
        examples=["UNDER_REVIEW"],
    )
    reason_code: str = Field(
        ...,
        min_length=1,
        max_length=128,
        description="Machine-readable reason for the transition (audit trail).",
        examples=["ESCALATED_BY_ANALYST"],
    )


class CaseStatusUpdateResponse(BaseModel):
    """Successful case status update including new ``case_history`` row id."""

    model_config = ConfigDict(extra="forbid")

    case_id: str = Field(..., description="``lifecycle_cases.case_id`` UUID string.")
    status: str = Field(..., description="Effective status after the transition.")
    history_row_id: int = Field(..., description="Primary key of the appended ``case_history`` row.")


class AiFeedbackRequest(BaseModel):
    """``POST /v1/ai/feedback`` — persist rejection reasons for offline RAG / fine-tuning pipelines."""

    model_config = ConfigDict(extra="forbid")

    rejection_reasons: list[str] = Field(
        ...,
        min_length=1,
        max_length=64,
        description="Human-provided rejection labels or free-text reasons (at least one).",
    )
    tenant_id: str | None = Field(
        default=None,
        max_length=128,
        description="Optional tenant scope for downstream joins.",
    )
    trace_id: str | None = Field(
        default=None,
        max_length=128,
        description="Optional decision / session trace identifier.",
    )
    entity_id: str | None = Field(
        default=None,
        max_length=128,
        description="Optional subject entity id.",
    )
    source: str | None = Field(
        default=None,
        max_length=64,
        description="Caller surface (e.g. ``shadow_llm``, ``copilot_ui``).",
    )
    context: str | None = Field(
        default=None,
        max_length=16_384,
        description="Optional short narrative or structured context blob.",
    )

    @field_validator("rejection_reasons")
    @classmethod
    def _reasons_non_empty_trimmed(cls, v: list[str]) -> list[str]:
        out: list[str] = []
        for raw in v:
            s = raw.strip()
            if not s:
                raise ValueError("each rejection_reason must be non-empty after trim")
            if len(s) > 4096:
                raise ValueError("rejection_reason exceeds max length (4096)")
            out.append(s)
        return out


class AiFeedbackResponse(BaseModel):
    """Acknowledgement after a feedback row is appended to JSONL."""

    model_config = ConfigDict(extra="forbid")

    ok: bool = Field(True, description="Always true on **200**.")
    feedback_id: str = Field(..., description="UUID for this stored row.")
    jsonl_path: str = Field(
        ...,
        description="Absolute path of the JSONL file after append (operators / tests).",
    )
