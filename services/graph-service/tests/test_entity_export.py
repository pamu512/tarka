"""Entity export for DSAR: the graph's personal data must be exportable.

DSAR access/portability previously exported SQL audit rows only — the graph
(entity nodes, edges to other entities, risk properties) held personal data
that was invisible to the export and survived erasure. This pins a dedicated
export route over existing primitives (deep context + one-hop subgraph).
"""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

_SRC = Path(__file__).resolve().parents[1]
for _p in (_SRC / "src",):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

os.environ.setdefault("ALLOW_INSECURE_NO_AUTH", "true")
os.environ.pop("API_KEYS", None)


_SUBGRAPH = {
    "nodes": [
        {"id": "u1", "label": "Person", "external_id": "u1", "risk": 0.4},
        {"id": "d1", "label": "Device", "external_id": "d1"},
    ],
    "edges": [
        {"from_id": "u1", "to_id": "d1", "rel": "USES", "since": "2026-01-01"},
    ],
}


class TestEntityExportRoute(unittest.IsolatedAsyncioTestCase):
    def test_export_returns_nodes_edges_and_context(self) -> None:
        from fastapi.testclient import TestClient

        import graph_service.main as m

        with (
            patch.object(m, "query_subgraph", AsyncMock(return_value=_SUBGRAPH)),
            patch.object(
                m, "query_entity_deep_context", AsyncMock(return_value={"entity_id": "u1"})
            ),
            TestClient(m.app) as client,
        ):
            r = client.get("/v1/entities/u1/export?tenant_id=t1")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["entity_id"], "u1")
        self.assertEqual(body["tenant_id"], "t1")
        self.assertEqual(len(body["nodes"]), 2)
        self.assertEqual(len(body["edges"]), 1)
        self.assertEqual(body["deep_context"], {"entity_id": "u1"})
        self.assertIn("exported_at", body)

    def test_export_404_when_entity_absent(self) -> None:
        from fastapi.testclient import TestClient

        import graph_service.main as m

        empty = {"nodes": [], "edges": []}
        with (
            patch.object(m, "query_subgraph", AsyncMock(return_value=empty)),
            patch.object(m, "query_entity_deep_context", AsyncMock(return_value=None)),
            TestClient(m.app) as client,
        ):
            r = client.get("/v1/entities/missing/export?tenant_id=t1")
        self.assertEqual(r.status_code, 404)


if __name__ == "__main__":
    unittest.main()
