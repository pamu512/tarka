"""Shared API response models for graph-service."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class EntityRiskResponse(BaseModel):
    """``GET /v1/analytics/entity-risk`` payload (Decision API evaluate contract)."""

    model_config = ConfigDict(extra="ignore")

    entity_id: str
    risk_score: float = Field(ge=0, le=100)
    risk_factors: list[str] = Field(default_factory=list)
    connected_flagged_count: int = Field(default=0, ge=0)
    community_size: int = Field(default=0, ge=0)
    neighbor_device_count: int = Field(
        default=0,
        ge=0,
        description="Distinct device_id values among 1-hop neighbors",
    )
    graph_checkpoint: str | None = None
    graph_profile: str | None = None
    graph_profile_multiplier: float | None = None
    graph_profile_max_neighbor_hops: int | None = None
    graph_data_as_of: str | None = None
    gnn_beta: dict[str, Any] | None = None
    scored: bool = False
    relation_count: int = Field(default=0, ge=0)
    relation_growth_1h: int = Field(default=0, ge=0)
    relation_growth_24h: int = Field(default=0, ge=0)
    named_edges: list[dict[str, Any]] = Field(default_factory=list)
    multi_id_user_ids: list[str] = Field(default_factory=list)
    roles: list[str] = Field(default_factory=list)
