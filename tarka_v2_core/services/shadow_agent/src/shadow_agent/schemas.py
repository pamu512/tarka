"""Pydantic schemas for shadow agent structured outputs."""

from __future__ import annotations

from typing import Any, Self
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
