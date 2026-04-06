from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    case_api_url: str = "http://localhost:8002"
    graph_service_url: str = ""
    decision_api_url: str = "http://localhost:8000"
    integration_profile_id: str = Field(
        default="tarka_reference_v1",
        description="Logical adapter profile id (exposed in /v1/integration for Pro/customer mapping).",
    )
    copilot_hide_tools_without_upstream: bool = Field(
        default=True,
        description=(
            "If true, omit tool definitions for upstreams that are not configured "
            "(empty CASE_API_URL, DECISION_API_URL, or GRAPH_SERVICE_URL)."
        ),
    )
    allowed_analysts: str = "*"
    openai_api_key: str = ""
    openai_base_url: str = "https://api.openai.com/v1"
    openai_model: str = "gpt-4o-mini"
    upstream_api_key: str = ""

    # --- Copilot hardening (env-tunable) ---
    copilot_injection_policy: Literal["reject", "sanitize"] = Field(
        default="sanitize",
        description="sanitize: redact patterns and continue; reject: block request on pattern match.",
    )
    copilot_include_platform_audit_in_prompt: bool = Field(
        default=True,
        description="If false, client platform_audit rows are ignored for the system prompt (supply-chain hardening).",
    )
    copilot_require_investigation_api_key: bool = Field(
        default=False,
        description="If true, x-api-key is mandatory (API_KEYS must be non-empty).",
    )
    copilot_max_tool_iterations: int = Field(default=10, ge=1, le=25)
    copilot_max_completion_tokens: int = Field(
        default=4096,
        ge=256,
        le=32000,
        description="Per LLM completion cap (limits token burn per round).",
    )
    copilot_enforce_tool_claim_grounding: bool = Field(
        default=True,
        description="Downgrade source=tool claims that do not overlap ids from successful tool I/O.",
    )
    copilot_disabled_tools: str = Field(
        default="",
        description="Comma-separated tool names to hide from the model (e.g. run_replay_ab_comparison).",
    )
    copilot_prompt_version: str = Field(
        default="3.2.0",
        description="Logical prompt / contract version (exposed in health and chat responses).",
    )
    copilot_structured_sections: bool = Field(
        default=True,
        description="Require FACTS/INFERENCES/UNKNOWNS/NEXT STEPS headings in assistant prose.",
    )
    copilot_enable_judge_pass: bool = Field(
        default=False,
        description="Second LLM pass to assess claim support vs tool JSON (extra latency/cost).",
    )
    openai_judge_model: str = Field(
        default="",
        description="Model for judge pass; empty = same as openai_model.",
    )
    copilot_judge_max_tokens: int = Field(default=900, ge=128, le=4096)
    copilot_reviewer_secret: str = Field(
        default="",
        description="If set with copilot_sensitive_tools, x-reviewer-secret header must match to expose those tools.",
    )
    copilot_sensitive_tools: str = Field(
        default="ingest_labeled_rows,run_replay_ab_comparison",
        description="Comma-separated tools hidden unless reviewer secret header matches.",
    )

    # --- RAG (knowledge memos) ---
    copilot_knowledge_embeddings: bool = Field(
        default=True,
        description="If true and OPENAI_API_KEY is set, embed memo chunks and use hybrid vector+keyword search.",
    )
    copilot_embedding_model: str = Field(
        default="text-embedding-3-small",
        description="OpenAI embedding model for knowledge ingest and search_knowledge.",
    )
    copilot_rag_keyword_weight: float = Field(
        default=0.35,
        ge=0.0,
        le=1.0,
        description="Weight for keyword overlap in hybrid RAG (rest is cosine similarity).",
    )

    # --- Assurance (stricter refusals + server-derived facts; not legal proof) ---
    copilot_assurance_mode: Literal["standard", "strict"] = Field(
        default="standard",
        description=(
            "strict: refuse assistant prose when tool errors are unacknowledged in prose or when any "
            "source=tool claim lacks deterministic token overlap with successful tool JSON."
        ),
    )
    copilot_derived_facts: bool = Field(
        default=False,
        description="Include derived_facts on each chat response (server-extracted scalars from successful tools).",
    )

    # --- Regional AI governance build (us | eu_uk | global) ---
    ai_governance_profile: str = Field(
        default="global",
        description="Deployment profile: us, eu_uk (EU+UK), or global — appends regional system-prompt block.",
    )

    # --- Evidence bundle (chat payload; v0 legacy + v1 provenance) ---
    copilot_evidence_bundle_format: Literal["v0", "v1", "dual"] = Field(
        default="dual",
        description="v0=legacy schema_hint only; v1=schema_id + provenance; dual=both for migration.",
    )
    agent_build_id: str = Field(
        default="",
        description="Image digest or Pro version string; emitted as agent_build in evidence_bundle v1 when set.",
    )
    copilot_evidence_redaction_level: Literal["none", "analyst_view", "export_safe"] = Field(
        default="analyst_view",
        description="Caps narrative/claims/refs in evidence_bundle_draft; export_safe is tightest.",
    )

    # --- Optional org analytics (PII-minimized events) ---
    copilot_analytics_enabled: bool = Field(
        default=False,
        description="If true, emit copilot.turn.completed and copilot.feedback.submitted (sink below).",
    )
    copilot_analytics_sink: Literal["log", "http"] = Field(
        default="log",
        description="log: structured INFO line; http: POST JSON to copilot_analytics_webhook_url.",
    )
    copilot_analytics_webhook_url: str = Field(
        default="",
        description="HTTPS endpoint for analytics JSON (when sink=http).",
    )
    copilot_analytics_hmac_secret: str = Field(
        default="",
        description="If set, include analyst_id_hash (HMAC-SHA256 truncated) on analytics payloads.",
    )


settings = Settings()
