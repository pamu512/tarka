"""Offline ring/collusion job. Never called from evaluate. Output is Observe-only."""

from __future__ import annotations

from typing import Any

from decision_api.l2_draft import L2DraftError, build_l2_draft, find_open_draft

JOB_REQUEST_SCHEMA = "tarka.ring_job_request/v1"
JOB_RESPONSE_SCHEMA = "tarka.ring_job_response/v1"


def _snapshot_edges(blob: Any) -> list[Any]:
    if not isinstance(blob, dict):
        return []
    raw = blob.get("edges")
    return list(raw) if isinstance(raw, list) else []


def edges_from_ring_request(body: dict[str, Any]) -> list[Any]:
    """Edges from raw `edges`, export `subgraph`, or labeled export rows.

    Offline sidecar only: never fetches neighbors. Empty GRAPH_SERVICE_URL
    stays hops-off; this helper does not invent a graph.
    """
    if isinstance(body.get("edges"), list):
        return list(body["edges"])
    if isinstance(body.get("subgraph"), dict):
        return _snapshot_edges(body["subgraph"])
    derived: list[Any] = []
    export = body.get("export")
    if isinstance(export, list):
        for row in export:
            if not isinstance(row, dict):
                continue
            snap = row.get("subgraph_snapshot")
            if not isinstance(snap, dict):
                nested = row.get("subgraph")
                snap = nested if isinstance(nested, dict) else {}
            derived.extend(_snapshot_edges(snap))
    return derived


def validate_ring_request(body: dict[str, Any]) -> dict[str, Any]:
    if str(body.get("schema_id") or "") != JOB_REQUEST_SCHEMA:
        raise ValueError("schema_id must be tarka.ring_job_request/v1")
    tenant = str(body.get("tenant_id") or "").strip()
    if not tenant:
        raise ValueError("tenant_id is required")
    if "subgraph" in body and not isinstance(body.get("subgraph"), dict):
        raise ValueError("subgraph must be a dict")
    if "labels" in body and not isinstance(body.get("labels"), list):
        raise ValueError("labels must be a list")
    if "export" in body and not isinstance(body.get("export"), list):
        raise ValueError("export must be a list")
    if "edges" in body and not isinstance(body.get("edges"), list):
        raise ValueError("edges must be a list")
    has_edges = isinstance(body.get("edges"), list)
    has_subgraph = isinstance(body.get("subgraph"), dict)
    has_export = isinstance(body.get("export"), list)
    if not (has_edges or has_subgraph or has_export):
        raise ValueError("subgraph/labels or edges required")
    if has_subgraph and not isinstance(body.get("labels"), list):
        raise ValueError("labels must be a list")
    return body


def run_ring_job(body: dict[str, Any]) -> dict[str, Any]:
    req = validate_ring_request(body)
    # ponytail: degree-count heuristic; real ring math is a later offline upgrade
    edges = edges_from_ring_request(req)
    counts: dict[str, int] = {}
    for edge in edges:
        if not isinstance(edge, dict):
            continue
        for key in ("src", "dst"):
            node = str(edge.get(key) or "").strip()
            if node:
                counts[node] = counts.get(node, 0) + 1
    tags = [
        {
            "entity_id": node,
            "tag": "ring_candidate",
            "ring_score": n / max(len(edges), 1),
        }
        for node, n in counts.items()
        if n >= 2
    ]
    ring_score = [
        {"entity_id": t["entity_id"], "ring_score": t["ring_score"]} for t in tags
    ]
    return {
        "schema_id": JOB_RESPONSE_SCHEMA,
        "tenant_id": req["tenant_id"],
        "ring_score": ring_score,
        "tags": tags,
        "live": False,
    }


def observe_drafts_from_ring(
    *,
    packs: list[dict[str, Any]],
    job: dict[str, Any],
    tenant_id: str,
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for tag in job.get("tags") or []:
        if not isinstance(tag, dict):
            continue
        eid = str(tag.get("entity_id") or "").strip()
        if not eid:
            continue
        hil = f"ring:{eid}"
        if find_open_draft(packs, leftover_id="", hil_event_id=hil):
            continue
        receipt = {
            "tenant_id": tenant_id,
            "entity_id": eid,
            "trace_id": hil,
            "user_id": eid,
        }
        try:
            pack = build_l2_draft(
                receipt=receipt,
                hil_event_id=hil,
                override_why="offline ring job",
                authored_by="seed",
                is_ai_authored=False,
                skip_backtest=True,
                actor="ring-job",
                skip_reason="ring job observe proposal",
            )
        except L2DraftError:
            continue
        pack["mode"] = "shadow"
        out.append(pack)
    return out
