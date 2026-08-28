"""Optional GRAPH_GNN_BETA_URL scorer. Empty URL / blocked gate → no score.

Never allow/deny. Never raise into evaluate. Graph-service already swallows
HTTP failures in score_graph_risk_beta.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from decision_api.gnn_loop.train import load_gate_artifact, score_mp_logreg


def gate_path() -> Path:
    raw = os.environ.get("GNN_LOOP_GATE_PATH", "").strip()
    if raw:
        return Path(raw)
    base = os.environ.get("CALIBRATION_DATA_DIR", "").strip()
    if base:
        return Path(base) / "gnn_serve_gate.json"
    return Path("gnn_serve_gate.json")


def load_serve_gate() -> dict[str, Any] | None:
    return load_gate_artifact(gate_path())


async def score_graph_risk(
    tenant_id: str,
    entity_id: str,
    subgraph: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Same contract as graph_service.score_graph_risk_beta's upstream."""
    _ = tenant_id
    try:
        gate = load_serve_gate()
        if not gate or not gate.get("serve_allowed"):
            return None
        weights = gate.get("weights") if isinstance(gate.get("weights"), list) else []
        try:
            bias = float(gate.get("bias") or 0.0)
        except (TypeError, ValueError):
            bias = 0.0
        snap = subgraph if isinstance(subgraph, dict) else {
            "vertices": [{"id": entity_id, "kind": "user", "role": "user"}],
            "edges": [],
        }
        score = score_mp_logreg(snap, [float(w) for w in weights], bias)
        score = max(0.0, min(100.0, float(score)))
        return {
            "model": "gnn-loop-mp-logreg",
            "risk_score": round(score, 2),
            "reasons": ["holdout_gated_overlay"],
            "gnn_claim_allowed": False,
        }
    except Exception:
        return None


def build_app():
    """Standalone FastAPI app for GRAPH_GNN_BETA_URL. Not mounted on evaluate."""
    from fastapi import FastAPI
    from pydantic import BaseModel, Field

    app = FastAPI(title="tarka-gnn-loop-scorer", docs_url=None, redoc_url=None)

    class GraphRiskBody(BaseModel):
        tenant_id: str = Field(min_length=1, max_length=128)
        entity_id: str = Field(min_length=1, max_length=512)
        subgraph: dict[str, Any] | None = None

    @app.post("/v1/graph-risk")
    async def graph_risk(body: GraphRiskBody) -> dict[str, Any]:
        out = await score_graph_risk(body.tenant_id, body.entity_id, body.subgraph)
        if out is None:
            return {
                "model": "gnn-loop-blocked",
                "risk_score": 0.0,
                "reasons": ["serve_blocked"],
                "scored": False,
                "gnn_claim_allowed": False,
            }
        return {**out, "scored": True}

    return app
