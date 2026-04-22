from __future__ import annotations

from typing import Any

"""Versioned graph → case explanation payload (xFraud-style why-links)."""
SCHEMA_ID = "tarka.graph_decision_explanation/v1"


def _factor_slug(code: str, idx: int) -> str:
    base = str(code).strip().replace("/", "_")[:80]
    if not base:
        base = "unknown"
    tail = f"g{idx}"
    return f"{tail}_{base}"


def build_graph_decision_explanation_v1(
    *,
    trace_id: str,
    tenant_id: str,
    entity_id: str,
    graph_risk: dict[str, Any] | None,
    graph_trace: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Structured factor → evidence mapping for analysts and case tooling.

    Returns None when graph risk was not available (evaluate skipped graph or graph outage).
    """
    if not isinstance(graph_risk, dict):
        return None
    factors_raw = graph_risk.get("risk_factors")
    if not isinstance(factors_raw, list):
        factors_raw = []
    if not factors_raw:
        try:
            score = float(graph_risk.get("risk_score", 0) or 0)
        except (TypeError, ValueError):
            score = 0.0
        if score <= 0:
            return None
        factors_raw = ["graph_score_only"]

    trace = graph_trace if isinstance(graph_trace, dict) else {}
    factors: list[dict[str, Any]] = []
    why_links: list[dict[str, Any]] = []

    codes = [str(x).strip() for x in factors_raw if str(x).strip()]
    for idx, code in enumerate(codes):
        fid = f"graph_factor:{_factor_slug(code, idx)}"
        factors.append(
            {
                "id": fid,
                "code": code,
                "source": "graph_entity_risk",
                "weight_hint": "primary" if idx == 0 else "supporting",
            }
        )
        ev: list[dict[str, str]] = [
            {"kind": "decision_trace", "ref": f"trace:{trace_id}", "role": "audit_row"},
            {"kind": "graph_subject", "ref": f"entity:{entity_id}", "role": "scored_node"},
        ]
        if ":" in code:
            ev.append({"kind": "graph_signal", "ref": f"metric:{code}", "role": "risk_factor"})
        why_links.append({"factor_id": fid, "evidence": ev})

    out: dict[str, Any] = {
        "schema_id": SCHEMA_ID,  # tarka.graph_decision_explanation/v1
        "trace_id": trace_id,
        "tenant_id": tenant_id,
        "subject": {"external_id": entity_id},
        "graph_trace": {"step": trace.get("step"), "status": trace.get("status"), "reason": trace.get("reason")},
        "factors": factors,
        "why_links": why_links,
        "case_ui": {
            "graph_subgraph_hint": "/v1/cases/{case_id}/graph",
            "audit_hint": f"/v1/audit/{trace_id}",
        },
    }
    beta = graph_risk.get("gnn_beta")
    if isinstance(beta, dict) and beta.get("model"):
        out["gnn_beta_overlay"] = {
            "model": str(beta.get("model", ""))[:64],
            "reasons": [str(x) for x in (beta.get("reasons") or []) if str(x)][:5],
        }
    return out
