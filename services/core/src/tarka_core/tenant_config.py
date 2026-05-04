"""Tenant-level configuration surfaced from Redis ``fraud:tenant_flags:{tenant_id}`` (and API defaults)."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, field_validator


class DataResidencyRegion(StrEnum):
    """Where tenant-controlled data may be processed for outbound vendor classification."""

    EU = "EU"
    US = "US"
    GLOBAL = "GLOBAL"


class TenantConfig(BaseModel):
    """Subset of tenant policy knobs used by services (extend over time)."""

    model_config = {"extra": "ignore"}

    data_residency_region: DataResidencyRegion = Field(
        default=DataResidencyRegion.GLOBAL,
        description="Primary residency for data-plane / vendor routing (EU tenants must not hit US-only OSINT).",
    )

    @field_validator("data_residency_region", mode="before")
    @classmethod
    def _coerce_region(cls, v: Any) -> Any:
        if v is None or v == "":
            return DataResidencyRegion.GLOBAL
        if isinstance(v, str):
            s = v.strip().upper()
            if s in ("EU", "US", "GLOBAL"):
                return s
        return v


def tenant_config_from_mapping(flags: dict[str, Any] | None) -> TenantConfig:
    """Build :class:`TenantConfig` from Redis tenant flags JSON (unknown keys ignored)."""
    if not flags:
        return TenantConfig()
    return TenantConfig.model_validate(flags)
