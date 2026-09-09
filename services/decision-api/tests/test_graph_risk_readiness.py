"""Option A: graph-risk challenger readiness (labels only — no train)."""

from __future__ import annotations

import pytest

from decision_api.gnn_loop.readiness import compute_graph_risk_readiness


def test_empty_tenant_is_not_ready_with_empty_overlay():
    out = compute_graph_risk_readiness(
        tenant_id="acme",
        receipts=[],
        labeled_rows=[],
        graph_service_url="",
        graph_gnn_beta_url="",
        gate=None,
    )
    assert out["schema_id"] == "tarka.graph_risk_challenger/v1"
    assert out["display_name"] == "Graph-risk / Ring-score challenger"
    assert out["subtitle"] == "mp-logreg holdout-gated · baseline heuristic_v1"
    assert out["graph_hop"] == "off"
    assert out["overlay_url"] == "empty"
    assert out["state"] == "collecting"
    assert out["trainable_rows"] == 0
    assert out["ready_to_train"] is False
    assert out["bars"]["min_trainable_rows"] == 8
    assert "GNN live" not in out["display_name"]


def test_ready_when_trainable_meets_code_floor():
    snap = {"edges": [{"src": "a", "dst": "b", "type": "USES_DEVICE"}], "vertices": []}
    rows = [
        {
            "trace_id": f"t{i}",
            "y_label": "1" if i % 2 else "0",
            "trainable": True,
            "subgraph_snapshot": snap,
        }
        for i in range(8)
    ]
    out = compute_graph_risk_readiness(
        tenant_id="acme",
        receipts=[{"trace_id": f"t{i}"} for i in range(10)],
        labeled_rows=rows,
        graph_service_url="http://graph:8080",
        graph_gnn_beta_url="",
        gate=None,
    )
    assert out["graph_hop"] == "on"
    assert out["overlay_url"] == "empty"
    assert out["trainable_rows"] == 8
    assert out["labeled_rows"] == 8
    assert out["receipt_count"] == 10
    assert out["ready_to_train"] is True
    assert out["state"] == "ready"


def test_gate_blocked_surfaces_aucs_without_claiming_live():
    out = compute_graph_risk_readiness(
        tenant_id="acme",
        receipts=[],
        labeled_rows=[],
        graph_service_url="http://graph:8080",
        graph_gnn_beta_url="http://gnn:8091",
        gate={
            "serve_allowed": False,
            "model_auc": 0.55,
            "heuristic_auc": 0.60,
            "reason": "holdout_did_not_beat_heuristic_v1",
        },
    )
    assert out["overlay_url"] == "shadow"
    assert out["state"] == "blocked"
    assert out["last_gate"]["serve_allowed"] is False
    assert out["last_gate"]["model_auc"] == 0.55
    assert out["last_gate"]["heuristic_auc"] == 0.60
    assert out["gnn_claim_allowed"] is False


def test_serve_allowed_with_url_is_shadow_not_live():
    out = compute_graph_risk_readiness(
        tenant_id="acme",
        receipts=[],
        labeled_rows=[
            {"y_label": "1", "trainable": True, "subgraph_snapshot": {"edges": [1]}}
        ]
        * 8,
        graph_service_url="http://graph:8080",
        graph_gnn_beta_url="http://gnn:8091",
        gate={
            "serve_allowed": True,
            "model_auc": 0.8,
            "heuristic_auc": 0.6,
            "reason": "ok",
        },
    )
    assert out["state"] == "shadow"
    assert out["overlay_url"] == "shadow"
    assert out["gnn_claim_allowed"] is False
    assert out["live_effect"] == "pack_promote_only"


@pytest.mark.asyncio
async def test_http_graph_risk_challenger(tmp_path, monkeypatch):
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient

    from decision_api.config import settings
    from decision_api.graph_risk_challenger_api import router

    monkeypatch.setenv("CALIBRATION_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("GRAPH_GNN_BETA_URL", raising=False)
    monkeypatch.setattr(settings, "graph_service_url", "")
    monkeypatch.setattr(settings, "rules_path", str(tmp_path))

    app = FastAPI()
    app.include_router(router)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/v1/ops/graph-risk-challenger", params={"tenant_id": "acme"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["display_name"] == "Graph-risk / Ring-score challenger"
    assert body["overlay_url"] == "empty"
    assert body["gnn_claim_allowed"] is False
    assert "GNN live" not in str(body)


def test_unset_url_serve_allowed_still_not_gnn_live():
    """G2.4: empty GRAPH_GNN_BETA_URL never becomes a live GNN claim."""
    out = compute_graph_risk_readiness(
        tenant_id="acme",
        receipts=[],
        labeled_rows=[],
        graph_service_url="http://graph:8080",
        graph_gnn_beta_url="",
        gate={
            "serve_allowed": True,
            "model_auc": 0.9,
            "heuristic_auc": 0.6,
            "reason": "ok",
        },
    )
    assert out["gnn_claim_allowed"] is False
    assert out["overlay_url"] == "empty"
    assert out["state"] != "live"
    assert out["live_effect"] == "pack_promote_only"
    assert "GNN live" not in str(out)
