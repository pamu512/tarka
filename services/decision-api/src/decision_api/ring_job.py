"""Offline ring/collusion job. Never called from evaluate. Output is Observe-only."""

from __future__ import annotations

from typing import Any

from decision_api.l2_draft import L2DraftError, build_l2_draft, find_open_draft

JOB_REQUEST_SCHEMA = "tarka.ring_job_request/v1"
JOB_RESPONSE_SCHEMA = "tarka.ring_job_response/v1"


def validate_ring_request(body: dict[str, Any]) -> dict[str, Any]:
    if str(body.get("schema_id") or "") != JOB_REQUEST_SCHEMA:
        raise ValueError("schema_id must be tarka.ring_job_request/v1")
    tenant = str(body.get("tenant_id") or "").strip()
    if not tenant:
        raise ValueError("tenant_id is required")
    edges = body.get("edges")
    if not isinstance(edges, list):
        raise ValueError("edges must be a list")
    return body


def run_ring_job(body: dict[str, Any]) -> dict[str, Any]:
    req = validate_ring_request(body)
    edges = req.get("edges") if isinstance(req.get("edges"), list) else []
    # ponytail: degree-count heuristic; real ring math is a later offline upgrade
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
    return {
        "schema_id": JOB_RESPONSE_SCHEMA,
        "tenant_id": req["tenant_id"],
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
