"""D7.3: empty GRAPH_SERVICE_URL is Hunt/hop plane-off. Evaluate must not wait."""

from __future__ import annotations

import pytest

from decision_api.gnn_loop.snapshot import fetch_written_subgraph, receipt_for_evaluate
from decision_api.graph_hop_contract import graph_pack_why


class _BoomHttp:
    async def get(self, *args, **kwargs):
        raise AssertionError("empty GRAPH_SERVICE_URL must not fetch Hunt/subgraph")


def test_empty_url_hop_is_structured_off_no_fabricated_nodes():
    why = graph_pack_why(
        {
            "named_edges": [{"from_id": "u1", "to_id": "d1", "type": "USES_DEVICE"}],
            "multi_id_user_ids": ["u2"],
            "nodes": [{"id": "invented"}],
        },
        graph_url="",
        tenant_id="t1",
        subject_id="u1",
    )
    hop = why["graph"]
    assert hop["status"] == "graph:missing"
    assert hop["named_edges"] == []
    assert hop["invented_edges"] is False
    assert hop.get("nodes") in (None, [])
    assert hop.get("vertices") in (None, [])
    applied = hop.get("depth_applied")
    if applied is not None:
        assert applied == 0


@pytest.mark.asyncio
async def test_empty_url_subgraph_proxy_does_not_invent_neighbors():
    got = await fetch_written_subgraph(
        _BoomHttp(),
        "",
        tenant_id="t1",
        entity_id="u1",
        depth=5,
    )
    assert got is None


@pytest.mark.asyncio
async def test_empty_url_evaluate_receipt_is_off_and_does_not_block():
    snap = await receipt_for_evaluate(
        _BoomHttp(),
        graph_service_url="",
        tenant_id="t1",
        entity_id="u1",
        user_id="u1",
        role="member",
        trace_id="tr-1",
        payload={"amount": 1},
        metadata={"party_graph": {"nodes": [{"id": "invented"}], "edges": [{"type": "USED"}]}},
    )
    assert snap["status"] == "graph:missing"
    assert snap["edges"] == []
    assert snap["vertices"] == []
    applied = snap.get("depth_applied")
    if applied is not None:
        assert applied == 0
