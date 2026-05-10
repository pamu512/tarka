"""Pydantic schemas for shadow agent structured outputs."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ShadowDecision(BaseModel):
    """Structured fraud decision envelope for LLM output validation."""

    model_config = ConfigDict(extra="forbid")

    transaction_id: UUID
    risk_score: float = Field(..., ge=0.0, le=100.0)
    is_fraud: bool
    reasoning: list[str]
    confidence_metrics: dict[str, Any]
