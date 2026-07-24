from __future__ import annotations

from .config import settings

"""
Graph analytics entrypoint: Neo4j (Cypher) or JanusGraph (Gremlin) per GRAPH_BACKEND.

Callers (main.py, tests) import from this module only — never from algorithms_neo4j
or algorithms_janus directly.
"""


def _clamp_depth(depth: int) -> int:
    """Shared depth bound for path-style analytics (matches neo4j algorithms)."""
    return max(1, min(int(depth), 5))


if settings.graph_backend == "janusgraph":
    from .algorithms_janus import (
        compute_entity_risk,
        detect_communities,
        detect_fraud_rings,
        explain_paths,
        find_shared_attributes,
        propagate_risk,
    )
elif settings.graph_backend == "age":
    from .algorithms_age import (
        compute_entity_risk,
        detect_communities,
        detect_fraud_rings,
        explain_paths,
        find_shared_attributes,
        propagate_risk,
    )
else:
    from .algorithms_neo4j import (
        compute_entity_risk,
        detect_communities,
        detect_fraud_rings,
        explain_paths,
        find_shared_attributes,
        propagate_risk,
    )

__all__ = [
    "_clamp_depth",
    "compute_entity_risk",
    "detect_communities",
    "detect_fraud_rings",
    "explain_paths",
    "find_shared_attributes",
    "propagate_risk",
]
