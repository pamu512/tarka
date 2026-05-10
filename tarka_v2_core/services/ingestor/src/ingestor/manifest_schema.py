"""Audit-first ingestion contract + manifest-related types.

Wire protobuf EvidenceManifest validation lived under ``tools/shadow`` / full ingestor;
this module exposes the lightweight ``TransactionSchema`` used by v2 integrity gates.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

import math
from pydantic import BaseModel, ConfigDict, Field, field_validator


class TransactionSchema(BaseModel):
    """
    Canonical transaction envelope for ingestion (aligned with Core ``/v1/decide`` payloads).

    Unknown fields are rejected so downstream normalization stays deterministic.
    """

    model_config = ConfigDict(extra="forbid")

    entity_id: UUID
    amount: float = Field(..., gt=0, description="Strictly positive finite amount.")
    timestamp: datetime
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("amount")
    @classmethod
    def _finite_amount(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("amount must be finite")
        return value
