"""Graph-derived feature registry with stable IDs and provenance (#65)."""

from __future__ import annotations

import json
from hashlib import sha256
from typing import Any

# v1.1 adds optional ``tags`` only; all v1.0 ``feature_id`` values remain stable.
GRAPH_FEATURES: list[dict[str, Any]] = [
    {
        "feature_id": "graph.ring_membership_count",
        "version": "1.0.0",
        "owner": "graph-service",
        "derivation": "Count of fraud-ring memberships involving the entity (see /v1/analytics/fraud-rings).",
        "decision_pipeline_key": "graph_features.ring_membership_count",
    },
    {
        "feature_id": "graph.shared_attribute_density",
        "version": "1.0.0",
        "owner": "graph-service",
        "derivation": "Normalized co-occurrence of high-risk shared attributes (device, IP bucket, etc.).",
        "decision_pipeline_key": "graph_features.shared_attribute_density",
    },
    {
        "feature_id": "graph.community_risk_score",
        "version": "1.0.0",
        "owner": "graph-service",
        "derivation": "Heuristic risk lift from community detection over neighborhood subgraph.",
        "decision_pipeline_key": "graph_features.community_risk_score",
    },
    {
        "feature_id": "graph.propagated_risk_peak",
        "version": "1.0.0",
        "owner": "graph-service",
        "derivation": "Max propagated risk score within configured hop depth from entity.",
        "decision_pipeline_key": "graph_features.propagated_risk_peak",
    },
]


def export_for_decision_pipeline() -> dict[str, Any]:
    """Contract surface for decision / ML pipelines (stable schema id)."""
    return {
        "schema": "tarka.graph_feature_registry/v1",
        "registry_version": "1.0.0",
        "features": list(GRAPH_FEATURES),
    }


def registry_content_digest() -> str:
    """Deterministic digest over canonical feature definitions (backward-compat guardrails)."""
    body = json.dumps(GRAPH_FEATURES, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return sha256(body).hexdigest()


def feature_ids() -> frozenset[str]:
    return frozenset(str(f["feature_id"]) for f in GRAPH_FEATURES)
