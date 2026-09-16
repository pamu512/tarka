"""Erasure symmetry: the graph must expose subject deletion over the wire.

DSAR access/portability now export graph data, but erasure anonymizes SQL rows
only — the graph entity survives erasure. ``delete_entity`` exists as a store
primitive with no HTTP surface. This pins ``DELETE /v1/entities/{id}``:
deletes (DETACH) and reports, 404 when the entity is absent.
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

_SUBGRAPH_PRESENT = {"nodes": [{"id": "u1", "external_id": "u1"}], "edges": []}
_SUBGRAPH_ABSENT = {"nodes": [], "edges": []}


class TestEntityDeleteRoute(unittest.IsolatedAsyncioTestCase):
    def test_delete_returns_deleted(self) -> None:
        from fastapi.testclient import TestClient

        import graph_service.main as m

        with (
            patch.object(m, "query_subgraph", AsyncMock(return_value=_SUBGRAPH_PRESENT)),
            patch.object(m, "delete_entity", AsyncMock(return_value=None)) as del_mock,
            TestClient(m.app) as client,
        ):
            r = client.delete("/v1/entities/u1?tenant_id=t1")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json(), {"entity_id": "u1", "tenant_id": "t1", "deleted": True})
        del_mock.assert_awaited_once()

    def test_delete_404_when_absent(self) -> None:
        from fastapi.testclient import TestClient

        import graph_service.main as m

        with (
            patch.object(m, "query_subgraph", AsyncMock(return_value=_SUBGRAPH_ABSENT)),
            patch.object(m, "delete_entity", AsyncMock(return_value=None)),
            TestClient(m.app) as client,
        ):
            r = client.delete("/v1/entities/missing?tenant_id=t1")
        self.assertEqual(r.status_code, 404)


if __name__ == "__main__":
    unittest.main()


class TestSearchKeysCleanup(unittest.IsolatedAsyncioTestCase):
    async def test_delete_route_cleans_search_index(self) -> None:
        from fastapi.testclient import TestClient

        import graph_service.main as m

        with (
            patch.object(m, "query_subgraph", AsyncMock(return_value=_SUBGRAPH_PRESENT)),
            patch.object(m, "delete_entity", AsyncMock(return_value=None)),
            patch("graph_service.search_keys.delete_search_keys", AsyncMock()) as keys_del,
            TestClient(m.app) as client,
        ):
            r = client.delete("/v1/entities/u1?tenant_id=t1")
        self.assertEqual(r.status_code, 200)
        keys_del.assert_awaited_once_with("t1", "u1")
