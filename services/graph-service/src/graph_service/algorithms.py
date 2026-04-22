from __future__ import annotations

from graph_service.config import settings

"""
Graph analytics entrypoint: Neo4j (Cypher) or JanusGraph (Gremlin) per GRAPH_BACKEND.

Callers (main.py, tests) import from this module only — never from algorithms_neo4j
or algorithms_janus directly.
"""

def _clamp_depth(depth: int) -> int:
    """Shared depth bound for path-style analytics (matches neo4j algorithms)."""
    return max(1, min(int(depth), 5))


if settings.graph_backend == "janusgraph":
    from graph_service.algorithms_janus import (
        compute_entity_risk,
        detect_communities,
        detect_fraud_rings,
        find_shared_attributes,
        propagate_risk,
    )
else:
    from graph_service.algorithms_neo4j import (
        compute_entity_risk,
        detect_communities,
        detect_fraud_rings,
        find_shared_attributes,
        propagate_risk,
    )

__all__ = [
    "_clamp_depth",
    "compute_entity_risk",
    "detect_communities",
    "detect_fraud_rings",
    "find_shared_attributes",
    "propagate_risk",
]
