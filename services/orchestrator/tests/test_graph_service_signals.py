"""Graph signals come from graph-service subgraph JSON."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

from graph.service_client import signals_for_entity


def test_signals_for_entity_reads_graph_service_edges() -> None:
    class _Http:
        def __init__(self) -> None:
            self.urls: list[tuple] = []

        async def get(self, url, params):
            self.urls.append((url, params))

            payload = {
                "nodes": [
                    {"id": "u1", "labels": ["Person"]},
                    {"id": "u2", "labels": ["Person"]},
                    {"id": "203.0.113.9", "labels": ["ip"]},
                    {"id": "card-9", "labels": ["payment"]},
                ],
                "edges": [
                    {"from_id": "u1", "to_id": "203.0.113.9", "type": "USED_IP"},
                    {"from_id": "u2", "to_id": "203.0.113.9", "type": "USED_IP"},
                    {"from_id": "u2", "to_id": "card-9", "type": "MADE_PAYMENT"},
                ],
            }
            return SimpleNamespace(status_code=200, json=lambda: payload)

    http = _Http()
    out = asyncio.run(signals_for_entity(http, tenant_id="acme", entity_id="u1"))
    assert http.urls[0][0].endswith("/v1/subgraph")
    assert http.urls[0][1]["depth"] == 2
    assert out["two_hop_distinct_cards_last_2h"] == 1
