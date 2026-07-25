"""HIL context override ingress schemas (Q2-E04)."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from orchestrator_analytics.hil_context_store import HilOverrideType
from config import get_settings
from schemas.operational import _IDEMPOTENCY_KEY_RE, _OPERATOR_ID_RE


class HilOverrideCreate(BaseModel):
    """``POST /v1/entities/{entity_id}/hil-overrides`` body."""

    model_config = ConfigDict(extra="forbid")

    idempotency_key: str = Field(..., min_length=1, max_length=255)
    tenant_id: str = Field(..., min_length=1, max_length=128)
    override_type: HilOverrideType
    scope_key: str = Field(..., min_length=1, max_length=256)
    expires_at: datetime | None = Field(
        default=None,
        description="UTC expiry; defaults to 90 days from ingest when omitted.",
    )
    analyst_rationale: str = Field(..., min_length=1, max_length=4096)
    analyst_id: str = Field(..., min_length=1, max_length=128)

    @field_validator("idempotency_key")
    @classmethod
    def _validate_idempotency_key(cls, v: str) -> str:
        token = v.strip()
        max_len = get_settings().operational_signal_idempotency_key_max_length
        if not token:
            raise ValueError("idempotency_key must be a non-empty string")
        if len(token) > max_len:
            raise ValueError(f"idempotency_key must be at most {max_len} characters")
        if not _IDEMPOTENCY_KEY_RE.fullmatch(token):
            raise ValueError("idempotency_key has invalid characters or shape")
        return token

    @field_validator("tenant_id", "scope_key")
    @classmethod
    def _strip_nonempty(cls, v: str) -> str:
        token = v.strip()
        if not token:
            raise ValueError("field must be non-empty")
        return token

    @field_validator("analyst_id")
    @classmethod
    def _validate_analyst_id(cls, v: str) -> str:
        token = v.strip()
        if not token:
            raise ValueError("analyst_id must be non-empty")
        if not _OPERATOR_ID_RE.fullmatch(token):
            raise ValueError("analyst_id has invalid characters or shape")
        return token

    @field_validator("analyst_rationale")
    @classmethod
    def _validate_rationale(cls, v: str) -> str:
        token = v.strip()
        if not token:
            raise ValueError("analyst_rationale must be non-empty")
        return token


class HilOverrideAcceptedResponse(BaseModel):
    """Successful HIL override ingest (ClickHouse row + operational signal audit id)."""

    model_config = ConfigDict(extra="forbid")

    event_id: UUID = Field(..., description="``operational_signals.id`` audit anchor.")
    override: dict[str, Any] = Field(
        ...,
        description="Normalized override row written to ClickHouse.",
    )


class HilOverrideListResponse(BaseModel):
    """Active (non-expired) overrides for an entity."""

    model_config = ConfigDict(extra="forbid")

    tenant_id: str
    entity_id: str
    overrides: list[dict[str, Any]] = Field(default_factory=list)
