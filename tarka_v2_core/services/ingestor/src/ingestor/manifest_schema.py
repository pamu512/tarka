"""Audit-first ingestion contract + manifest-related types.

Wire protobuf EvidenceManifest validation lived under ``tools/shadow`` / full ingestor;
this module exposes the lightweight ``TransactionSchema`` used by v2 integrity gates.
"""

from __future__ import annotations

import math
from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class TransactionSchema(BaseModel):
    """
    Canonical transaction envelope for ingestion (aligned with Core ``/v1/decide`` payloads).

    Unknown fields are rejected so downstream normalization stays deterministic.
    """

    model_config = ConfigDict(extra="forbid")

    entity_id: UUID = Field(
        ...,
        description="Unique transaction identifier (UUID). Must match across retries for the same payment attempt.",
    )
    amount: float = Field(
        ...,
        gt=0,
        description="Strictly positive finite monetary amount in the transaction currency (not NaN or infinite).",
    )
    timestamp: datetime = Field(
        ...,
        description="Transaction time as ISO 8601 datetime (UTC recommended).",
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Optional structured context (channel, device, merchant tags, etc.). "
            "Extra keys are allowed inside `metadata`; the top-level envelope rejects unknown fields."
        ),
    )

    @field_validator("amount")
    @classmethod
    def _finite_amount(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("amount must be finite")
        return value
