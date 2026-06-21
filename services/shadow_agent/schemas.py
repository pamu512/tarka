"""Pydantic schemas for shadow agent structured outputs."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Self
from uuid import UUID

from ingestor.manifest_schema import TransactionSchema
from pydantic import BaseModel, ConfigDict, Field, model_validator


class ShadowDecision(BaseModel):
    """Structured fraud decision envelope for LLM output validation."""

    model_config = ConfigDict(extra="forbid")

    transaction_id: UUID
    risk_score: float = Field(..., ge=0.0, le=100.0)
    is_fraud: bool
    reasoning: list[str]
    confidence_metrics: dict[str, Any]
    ai_reasoning: str = Field(
        default="",
        max_length=12_000,
        description=(
            "Primary narrative rationale for reviewers. When GRAPH CONTEXT is supplied, cite "
            "topology signals here (including **Linked to Blocked Node** when applicable)."
        ),
    )

    @model_validator(mode="after")
    def _default_ai_reasoning_from_reasoning(self) -> Self:
        if self.ai_reasoning.strip():
            return self
        joined = "; ".join(self.reasoning).strip()
        self.ai_reasoning = joined if joined else "—"
        return self


class ShadowAnalyzeEnvelope(BaseModel):
    """Wire format for ``POST /v1/analyze`` when the orchestrator injects graph signals."""

    model_config = ConfigDict(extra="forbid")

    transaction: TransactionSchema
    graph_context: dict[str, Any] | None = Field(
        default=None,
        description="Structured graph topology signals (Neo4j ``get_graph_signals`` + hardware risk).",
    )


class HypothesisReport(BaseModel):
    """Scout-generated promotion candidate for a coordinated-abuse pattern (Prompt 194)."""

    model_config = ConfigDict(extra="forbid")

    report_id: str = Field(..., min_length=1, max_length=64)
    strategy: Literal["coordinated_burst"] = "coordinated_burst"
    fingerprint_kind: Literal["canvas_hash", "webgl_vendor"]
    fingerprint_value: str = Field(..., min_length=1, max_length=4096)
    distinct_account_count: int = Field(..., ge=1)
    window_start_utc: datetime
    window_end_utc: datetime
    account_ids: list[str] = Field(default_factory=list, max_length=64)
    narrative: str = Field(..., min_length=1, max_length=16_000)
    confidence: float = Field(..., ge=0.0, le=1.0)
    suggested_rule: dict[str, Any] | None = Field(
        default=None,
        description="Optional shadow rule JSON derived from the burst fingerprint.",
    )
    saarthi_narrative: str | None = Field(
        default=None,
        max_length=4_000,
        description="Two-sentence Saarthi (Gemini) analyst summary (Prompt 195).",
    )
    saarthi_attribution_engine: str | None = Field(
        default=None,
        max_length=32,
        description="``gemini`` or ``fallback`` for ``saarthi_narrative``.",
    )
    analyst_suggestion_allowed: bool = Field(
        default=False,
        description="True only when 7-day DuckDB backtest FPR is below 0.1% (Prompt 196).",
    )
    backtest_false_positive_rate: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="``fp / (fp + tn)`` over the backtest lookback window.",
    )
    backtest_lookback_days: int | None = Field(default=None, ge=1)
    backtest_validation: dict[str, Any] | None = Field(
        default=None,
        description="Full backtest gate payload from ``validate_hypothesis_backtest``.",
    )


class SARReportSchema(BaseModel):
    """Structured Suspicious Activity Report (SAR) draft for LLM / pipeline validation."""

    model_config = ConfigDict(extra="forbid")

    primary_suspect: str = Field(
        ...,
        min_length=1,
        max_length=2048,
        description="Identified or suspected subject (person, business, or account token).",
    )
    laundering_volume: float = Field(
        ...,
        ge=0.0,
        description="Estimated suspicious funds movement in a single reporting currency (e.g. USD).",
    )
    narrative: str = Field(
        ...,
        min_length=1,
        max_length=50_000,
        description="Factual narrative suitable for regulatory filing (who, what, when, how).",
    )
    confidence: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Model or analyst confidence in this SAR draft, normalized to [0, 1].",
    )
