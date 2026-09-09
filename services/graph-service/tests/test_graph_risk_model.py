"""GRAPH_GNN_BETA_URL empty → no beta score (heuristic path stays on)."""

from __future__ import annotations

import pytest

from graph_service.graph_risk_model import score_graph_risk_beta


def test_default_gnn_beta_url_is_empty(monkeypatch):
    monkeypatch.delenv("GRAPH_GNN_BETA_URL", raising=False)
    from graph_service.config import Settings

    assert Settings().graph_gnn_beta_url == ""


@pytest.mark.asyncio
async def test_empty_gnn_beta_url_returns_none(monkeypatch):
    from graph_service import graph_risk_model as grm

    monkeypatch.setattr(grm.settings, "graph_gnn_beta_url", "")
    out = await score_graph_risk_beta("t", "e1")
    assert out is None
