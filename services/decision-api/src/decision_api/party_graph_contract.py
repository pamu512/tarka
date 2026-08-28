"""Host party_graph contract — quality assessment for ring_score inputs.

Best decision: refuse to pretend sparse/host-garbage graphs are collusion-grade.
Does not invent edges; scores readiness of what the host supplied.
"""

from __future__ import annotations

from typing import Any

from graph_contract import BRIDGE_VTYPES

SCHEMA_ID = "tarka.party_graph_contract/v1"
METHOD = "graph_quality_v1"

# Host-supplied roles are not a second ontology. Any non-empty role that is not a
# bridge vtype counts as a person-role. Core does not hardcode diner/driver/merchant.

_BRIDGE = frozenset({*BRIDGE_VTYPES, "payment_instrument"})


def _extract_graph(
    payload: dict[str, Any] | None, metadata: dict[str, Any] | None
) -> dict[str, Any] | None:
    for src in (metadata, payload):
        if not isinstance(src, dict):
            continue
        g = src.get("party_graph") or src.get("graph")
        if isinstance(g, dict):
            return g
    return None


def assess_party_graph_quality(
    *,
    payload: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
    graph: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Return quality report or None if no graph block."""
    g = graph if isinstance(graph, dict) else _extract_graph(payload, metadata)
    if g is None:
        return None

    nodes_raw = g.get("nodes") if isinstance(g.get("nodes"), list) else []
    edges_raw = g.get("edges") if isinstance(g.get("edges"), list) else []
    issues: list[str] = []
    roles: set[str] = set()
    node_ids: set[str] = set()
    role_missing = 0
    for n in nodes_raw:
        if not isinstance(n, dict):
            continue
        nid = str(n.get("id") or "").strip()
        if not nid:
            continue
        node_ids.add(nid)
        role = str(n.get("role") or "").strip().lower()
        if not role:
            role_missing += 1
            issues.append("node_missing_role")
        else:
            roles.add(role)

    edge_types: set[str] = set()
    ts_n = 0
    dangling = 0
    for e in edges_raw:
        if not isinstance(e, dict):
            continue
        src = str(e.get("src") or e.get("from") or "").strip()
        dst = str(e.get("dst") or e.get("to") or "").strip()
        et = str(e.get("type") or e.get("rel") or "").strip().upper()
        if et:
            edge_types.add(et)
        if e.get("ts") is not None or e.get("age_hours") is not None:
            ts_n += 1
        if src and dst and (src not in node_ids or dst not in node_ids):
            # endpoints may be implied — count soft
            dangling += 1

    bridge_roles = roles & _BRIDGE
    person_roles = {r for r in roles if r and r not in _BRIDGE}
    n_nodes = len(node_ids)
    n_edges = len(edges_raw)

    if n_nodes < 2:
        issues.append("too_few_nodes")
    if n_edges < 1:
        issues.append("no_edges")
    if not bridge_roles and n_edges >= 1:
        issues.append("no_bridge_roles")
    if len(person_roles) < 2 and n_nodes >= 2:
        issues.append("single_person_role_only")
    if n_edges >= 3 and ts_n == 0:
        issues.append("no_edge_timestamps")
    if role_missing:
        issues.append(f"roles_missing:{role_missing}")

    # 0–100 readiness (not a fraud score)
    score = 40.0
    if n_nodes >= 3:
        score += 10
    if n_edges >= 2:
        score += 10
    if bridge_roles:
        score += 15
    if len(person_roles) >= 2:
        score += 15
    if ts_n >= 1:
        score += 10
    if "USES_DEVICE" in edge_types or "SEEN_AT" in edge_types:
        score += 10
    if "no_edges" in issues or "too_few_nodes" in issues:
        score = min(score, 25.0)
    if "no_bridge_roles" in issues and "single_person_role_only" in issues:
        score = min(score, 35.0)
    score = max(0.0, min(100.0, score))

    production_ready = (
        score >= 70.0
        and "no_edges" not in issues
        and "too_few_nodes" not in issues
        and bool(bridge_roles or len(person_roles) >= 2)
    )

    return {
        "schema_id": SCHEMA_ID,
        "method": METHOD,
        "quality_0_100": round(score, 2),
        "production_ready": production_ready,
        "node_count": n_nodes,
        "edge_count": n_edges,
        "person_role_count": len(person_roles),
        "bridge_role_count": len(bridge_roles),
        "edge_types": sorted(edge_types)[:32],
        "timestamped_edges": ts_n,
        "issues": list(dict.fromkeys(issues))[:24],
        "honesty": {
            "host_supplied_only": True,
            "invented_edges": False,
            "gnn_claim_allowed": False,
            "live_device_edges": False,
        },
    }
