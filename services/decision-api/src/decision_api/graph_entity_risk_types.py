"""Typed contract for graph-service ``GET /v1/analytics/entity-risk`` payloads."""

from __future__ import annotations

from typing import Any, TypedDict

# Distinct neighbor device_id count at or above this value → graph:neighbor_device_count_high
NEIGHBOR_DEVICE_COUNT_HIGH_THRESHOLD = 3


class GraphEntityRiskPayload(TypedDict, total=False):
    entity_id: str
    risk_score: float
    risk_factors: list[str]
    connected_flagged_count: int
    community_size: int
    neighbor_device_count: int
    graph_checkpoint: str | None
    graph_profile: str | None
    graph_profile_multiplier: float | None
    graph_profile_max_neighbor_hops: int | None
    graph_data_as_of: str | None
    gnn_beta: dict[str, Any] | None
