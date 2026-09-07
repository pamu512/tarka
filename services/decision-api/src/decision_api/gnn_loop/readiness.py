"""Graph-risk / Ring-score challenger readiness (Option A).

Labels + bars only. Does not train and does not set GRAPH_GNN_BETA_URL.
Desk copy never claims \"GNN live\".
"""

from __future__ import annotations

import os
import statistics
from datetime import datetime
from typing import Any, Mapping, Sequence

from decision_api.gnn_loop import GATE_SCHEMA_ID
from decision_api.gnn_loop.export import export_labeled_rows
from decision_api.gnn_loop.receipts import load_receipts
from decision_api.gnn_loop.train import load_gate_artifact
from decision_api.y_label_store import _data_dir

SCHEMA_ID = "tarka.graph_risk_challenger/v1"
DISPLAY_NAME = "Graph-risk / Ring-score challenger"
SUBTITLE = "mp-logreg holdout-gated · baseline heuristic_v1"

# Code floor (train_and_gate) + Track-3 planning defaults (glass only).
MIN_TRAINABLE_ROWS = 8
PLANNING_MIN_LABELS = 1000
PLANNING_MIN_EDGED_EVENTS = 100_000


def _parse_ts(raw: Any) -> datetime | None:
    text = str(raw or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


def _p90(values: list[float]) -> float | None:
    if not values:
        return None
    if len(values) == 1:
        return values[0]
    return float(statistics.quantiles(values, n=100, method="inclusive")[89])


def _overlay_state(url: str, *, serve_allowed: bool | None) -> str:
    if not (url or "").strip():
        return "empty"
    # URL set = overlay available for shadow; never a "live" claim.
    return "shadow" if serve_allowed is not False else "shadow"


def _state(
    *,
    ready_to_train: bool,
    serve_allowed: bool | None,
    overlay_set: bool,
) -> str:
    if serve_allowed is False and overlay_set:
        return "blocked"
    if serve_allowed is True and overlay_set:
        return "shadow"
    if serve_allowed is False and not overlay_set:
        # Trained but blocked — still blocked even without URL.
        return "blocked"
    if serve_allowed is True and not overlay_set:
        return "trained"
    if ready_to_train:
        return "ready"
    return "collecting"


def compute_graph_risk_readiness(
    *,
    tenant_id: str,
    receipts: Sequence[Mapping[str, Any]],
    labeled_rows: Sequence[Mapping[str, Any]],
    graph_service_url: str,
    graph_gnn_beta_url: str,
    gate: Mapping[str, Any] | None,
) -> dict[str, Any]:
    tid = (tenant_id or "").strip()
    hop_on = bool((graph_service_url or "").strip())
    overlay = (graph_gnn_beta_url or "").strip()
    trainable = [
        r
        for r in labeled_rows
        if r.get("trainable") is not False
        and isinstance((r.get("subgraph_snapshot") or {}).get("edges"), list)
        and (r.get("subgraph_snapshot") or {}).get("edges")
    ]
    labeled_n = len(labeled_rows)
    trainable_n = len(trainable)
    receipt_n = len(receipts)
    ready = trainable_n >= MIN_TRAINABLE_ROWS

    lags: list[float] = []
    for row in labeled_rows:
        if not isinstance(row, Mapping):
            continue
        decided = _parse_ts(row.get("decided_at") or row.get("created_at"))
        labeled = _parse_ts(row.get("labeled_at"))
        if decided is None or labeled is None:
            continue
        lags.append(max(0.0, (labeled - decided).total_seconds()))

    serve_allowed: bool | None = None
    last_gate: dict[str, Any] = {
        "serve_allowed": None,
        "model_auc": None,
        "heuristic_auc": None,
        "reason": None,
        "schema_id": GATE_SCHEMA_ID,
    }
    if isinstance(gate, Mapping) and gate:
        serve_allowed = bool(gate.get("serve_allowed"))
        last_gate = {
            "serve_allowed": serve_allowed,
            "model_auc": gate.get("model_auc"),
            "heuristic_auc": gate.get("heuristic_auc"),
            "reason": str(gate.get("reason") or "") or None,
            "schema_id": str(gate.get("schema_id") or GATE_SCHEMA_ID),
        }

    labeled_pct = (labeled_n / receipt_n) if receipt_n else 0.0
    trainable_pct = (trainable_n / labeled_n) if labeled_n else 0.0
    return {
        "schema_id": SCHEMA_ID,
        "tenant_id": tid,
        "display_name": DISPLAY_NAME,
        "subtitle": SUBTITLE,
        "graph_hop": "on" if hop_on else "off",
        "overlay_url": _overlay_state(overlay, serve_allowed=serve_allowed),
        "overlay_url_set": bool(overlay),
        "state": _state(
            ready_to_train=ready,
            serve_allowed=serve_allowed,
            overlay_set=bool(overlay),
        ),
        "receipt_count": receipt_n,
        "labeled_rows": labeled_n,
        "labeled_pct": round(labeled_pct, 4),
        "trainable_rows": trainable_n,
        "trainable_pct": round(trainable_pct, 4),
        "ready_to_train": ready,
        "p90_label_lag_seconds": _p90(lags),
        "bars": {
            "min_trainable_rows": MIN_TRAINABLE_ROWS,
            "planning_min_labels": PLANNING_MIN_LABELS,
            "planning_min_edged_events": PLANNING_MIN_EDGED_EVENTS,
        },
        "last_gate": last_gate,
        "gnn_claim_allowed": False,
        "live_effect": "pack_promote_only",
        "note": "Empty overlay URL is evaluate-only heuristic_v1. Model never ALLOW/DENY/Promote.",
    }


def default_gate_path() -> Any:
    from pathlib import Path

    env = os.environ.get("GNN_LOOP_GATE_PATH", "").strip()
    if env:
        return Path(env)
    return _data_dir() / "gnn_serve_gate.json"


def build_graph_risk_readiness(tenant_id: str) -> dict[str, Any]:
    """Load receipts/labels/gate from disk for the tenant."""
    from decision_api.config import settings
    from decision_api.gnn_loop.lifecycle import load_lifecycle

    receipts = load_receipts(tenant_id)
    rows = export_labeled_rows(tenant_id, receipts)
    gate = load_gate_artifact(default_gate_path())
    life = load_lifecycle(tenant_id)
    overlay = os.environ.get("GRAPH_GNN_BETA_URL", "").strip()
    if not overlay and life.get("shadow_enabled") and str(life.get("shadow_url") or "").strip():
        overlay = str(life.get("shadow_url") or "").strip()
    out = compute_graph_risk_readiness(
        tenant_id=tenant_id,
        receipts=receipts,
        labeled_rows=rows,
        graph_service_url=str(getattr(settings, "graph_service_url", "") or ""),
        graph_gnn_beta_url=overlay,
        gate=gate,
    )
    # Lifecycle state wins when more specific (trained/blocked/shadow/retired).
    life_state = str(life.get("state") or "").strip()
    if life_state in {"trained", "blocked", "shadow", "retired", "live_via_pack"}:
        out["state"] = life_state
    out["lifecycle"] = {
        "shadow_enabled": bool(life.get("shadow_enabled")),
        "shadow_url": str(life.get("shadow_url") or ""),
        "last_actor": life.get("last_actor"),
        "note": life.get("note"),
    }
    return out
