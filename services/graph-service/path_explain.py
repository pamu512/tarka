from __future__ import annotations

from typing import Any

SCHEMA_ID = "tarka.graph_path_explanation/v1"
_MAX_NOTE_LEN = 2000


def _hop_from_chain(
    node_chain: list[str],
    rel_types: list[str],
    entity_labels: list[str] | None,
) -> list[dict[str, Any]]:
    hops: list[dict[str, Any]] = []
    labels = entity_labels or []
    for i, nid in enumerate(node_chain):
        rel = None
        if i > 0 and i - 1 < len(rel_types):
            rel = str(rel_types[i - 1])
        hop_labels = labels if i == len(node_chain) - 1 and labels else []
        hops.append(
            {
                "entity_id": str(nid),
                "labels": list(hop_labels),
                "relationship": rel,
            }
        )
    return hops


def _path_description(node_chain: list[str], rel_types: list[str]) -> str:
    if not node_chain:
        return ""
    parts: list[str] = []
    for i, nid in enumerate(node_chain):
        parts.append(f"({nid})")
        if i < len(rel_types):
            parts.append(f"-[{rel_types[i]}]->")
    return " ".join(parts)


def _risk_reasons(distance: int, score: float, labels: list[str]) -> list[str]:
    reasons: list[str] = [f"hop_distance:{distance}", f"propagated_score:{score}"]
    risky = {t.lower() for t in labels} & {
        "fraud",
        "suspicious",
        "flagged",
        "blocked",
        "chargedback",
    }
    if risky:
        reasons.append(f"neighbor_tags:{','.join(sorted(risky))}")
    if distance <= 1:
        reasons.append("direct_neighbor")
    elif distance == 2:
        reasons.append("two_hop_exposure")
    return reasons


def _risk_narrative(
    from_entity_id: str,
    ranked_paths: list[dict[str, Any]],
    to_entity_id: str | None,
) -> str:
    if not ranked_paths:
        if to_entity_id:
            return (
                f"No graph path found from {from_entity_id} to {to_entity_id} "
                "within the configured hop budget."
            )
        return f"No outward risk paths discovered from {from_entity_id}."

    top = ranked_paths[0]
    target = top.get("target_entity_id") or top.get("entity_id")
    dist = top.get("distance", 0)
    score = top.get("propagated_risk_score", 0)
    desc = top.get("path_description", "")
    if to_entity_id:
        return (
            f"Shortest-risk path from {from_entity_id} to {to_entity_id} spans "
            f"{dist} hop(s) with propagated score {score}. Path: {desc}"
        )
    lead = ranked_paths[:3]
    summaries = [
        f"{p.get('entity_id')} (d={p.get('distance')}, score={p.get('propagated_risk_score')})"
        for p in lead
    ]
    return f"Top outward risk exposures from {from_entity_id}: " + "; ".join(summaries) + "."


def assemble_path_explanation(
    tenant_id: str,
    from_entity_id: str,
    propagation_rows: list[dict[str, Any]],
    *,
    to_entity_id: str | None = None,
    limit: int = 10,
    subject_risk: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build ranked path explanation from propagate_risk-style rows."""
    lim = max(1, min(int(limit), 25))
    target = (to_entity_id or "").strip() or None

    paths: list[dict[str, Any]] = []
    for row in propagation_rows:
        eid = str(row.get("entity_id") or "").strip()
        if not eid:
            continue
        if target and eid != target:
            continue
        node_chain = row.get("node_chain")
        rel_types = row.get("rel_types")
        if isinstance(node_chain, list) and node_chain:
            chain = [str(x) for x in node_chain]
            rels = [str(x) for x in rel_types] if isinstance(rel_types, list) else []
        else:
            chain = [from_entity_id, eid]
            rels = []
        labels = row.get("entity_labels")
        ent_labels = [str(x) for x in labels] if isinstance(labels, list) else []
        dist = int(row.get("distance") or 1)
        score = float(row.get("propagated_risk_score") or 0.0)
        desc = row.get("path_description") or _path_description(chain, rels)
        paths.append(
            {
                "entity_id": eid,
                "target_entity_id": eid,
                "distance": dist,
                "propagated_risk_score": score,
                "path_description": desc,
                "hops": _hop_from_chain(chain, rels, ent_labels),
                "reasons": _risk_reasons(dist, score, ent_labels),
            }
        )

    paths.sort(
        key=lambda p: (-float(p.get("propagated_risk_score") or 0), int(p.get("distance") or 99)),
    )
    ranked = paths[:lim]

    summary: dict[str, Any] = {
        "path_count": len(ranked),
        "max_propagated_score": max(
            (float(p.get("propagated_risk_score") or 0) for p in ranked),
            default=0.0,
        ),
        "flagged_intermediates": [
            p.get("entity_id")
            for p in ranked
            if any(r.startswith("neighbor_tags:") for r in (p.get("reasons") or []))
        ],
    }
    if subject_risk:
        summary["subject_risk_score"] = subject_risk.get("risk_score")
        summary["subject_risk_factors"] = list(subject_risk.get("risk_factors") or [])

    return {
        "schema_id": SCHEMA_ID,
        "tenant_id": tenant_id,
        "subject": from_entity_id,
        "target": target,
        "paths": ranked,
        "risk_narrative": _risk_narrative(from_entity_id, ranked, target),
        "summary": summary,
    }


def validate_annotation_map(raw: dict[str, Any]) -> dict[str, str]:
    out: dict[str, str] = {}
    for key, val in raw.items():
        node_id = str(key).strip()
        if not node_id or len(node_id) > 512:
            continue
        note = str(val).strip()
        if not note:
            continue
        out[node_id] = note[:_MAX_NOTE_LEN]
    if len(out) > 500:
        raise ValueError("too many annotation entries (max 500)")
    return out
