"""Mule path is a read of TRANSACTED edges."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_MOD_PATH = (
    Path(__file__).resolve().parents[1] / "src" / "integration_ingress" / "mule_path_visualizer.py"
)
_spec = importlib.util.spec_from_file_location("mule_path_visualizer", _MOD_PATH)
assert _spec and _spec.loader
_mod = importlib.util.module_from_spec(_spec)
sys.modules["mule_path_visualizer"] = _mod
_spec.loader.exec_module(_mod)


def test_no_edges_returns_empty_path():
    payload = _mod.build_mule_path_from_edges(
        tenant_id="acme",
        origin_entity_id="fraud_frank",
        mule_entity_id=None,
        edges=[],
    )
    assert payload["source"] == "graph"
    assert payload["hops"] == []
    assert payload["transfers"] == []
    assert payload["summary"]["total_outflow"] == 0.0


def test_transacted_edges_sum_amounts_and_filter_mule():
    edges = [
        {
            "type": "TRANSACTED",
            "from_id": "fraud_frank",
            "to_id": "mule_ivan",
            "properties": {"amount": 1000, "currency": "USD", "trace_id": "tr-1"},
        },
        {
            "type": "TRANSACTED",
            "from_id": "fraud_frank",
            "to_id": "mule_ivan",
            "properties": {"amount": 500, "currency": "USD", "trace_id": "tr-2"},
        },
        {
            "type": "TRANSACTED",
            "from_id": "fraud_frank",
            "to_id": "someone_else",
            "properties": {"amount": 9, "currency": "USD", "trace_id": "tr-3"},
        },
        {
            "type": "USED_DEVICE",
            "from_id": "fraud_frank",
            "to_id": "dev_emulator_003",
            "properties": {},
        },
    ]
    payload = _mod.build_mule_path_from_edges(
        tenant_id="demo",
        origin_entity_id="fraud_frank",
        mule_entity_id="mule_ivan",
        edges=edges,
    )
    assert payload["source"] == "graph"
    assert [h["entity_id"] for h in payload["hops"]] == ["fraud_frank", "mule_ivan"]
    assert payload["summary"]["total_outflow"] == 1500.0
    assert payload["summary"]["payout_amount"] == 0.0
    assert len(payload["transfers"]) == 2


def test_blank_origin_is_empty():
    payload = _mod.build_mule_path_from_edges(
        tenant_id="demo",
        origin_entity_id="  ",
        mule_entity_id=None,
        edges=[{"type": "TRANSACTED", "from_id": "a", "to_id": "b", "properties": {"amount": 1}}],
    )
    assert payload["hops"] == []


@pytest.mark.asyncio
async def test_unset_graph_url_does_not_invent_a_path(monkeypatch):
    monkeypatch.delenv("GRAPH_SERVICE_URL", raising=False)
    payload = await _mod.load_mule_path(
        tenant_id="acme",
        origin_entity_id="fraud_frank",
        mule_entity_id=None,
        graph_url="",
    )
    assert payload["source"] == "graph:unconfigured"
    assert payload["hops"] == []
