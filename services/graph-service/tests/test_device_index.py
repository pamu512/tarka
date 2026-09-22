"""R3: entity-risk shared-device index (Postgres side-table, search_keys pattern).

The AGE cypher for shared_device_count scans every tenant node per compute
(O(N) per entity, O(N^2) per refresh pass). A device index table keyed
(tenant_id, device_id) makes the lookup O(devices-per-device). These tests pin:
  - the index module API (ensure/upsert/delete/count) exists,
  - count semantics (self excluded, other tenants excluded),
  - upsert_entity maintains it fail-soft (search_keys precedent),
  - compute_entity_risk reads the count from the index, not a tenant scan,
  - delete sweeps index rows (delete must sweep every secondary store).
"""

import os
import types
import unittest
from contextlib import asynccontextmanager

os.environ.setdefault("ALLOW_INSECURE_NO_AUTH", "true")
os.environ.pop("API_KEYS", None)
from unittest.mock import AsyncMock, patch

_SUBGRAPH = {"nodes": [{"id": "u1", "external_id": "u1"}], "edges": []}


class _Conn:
    def __init__(self, fetchval=0, execute=None):
        self.fetchval = AsyncMock(return_value=fetchval)
        self.execute = execute or AsyncMock()
        self.fetchrow = AsyncMock(return_value=None)


class _Pool:
    def __init__(self, conn):
        self._conn = conn
        self.acquire = lambda: _Ctx(self._conn)


class _Ctx:
    def __init__(self, conn):
        self._conn = conn

    async def __aenter__(self):
        return self._conn

    async def __aexit__(self, *a):
        return False


def _row(**kw):
    defaults = {
        "tags": '["fraud"]',
        "conn_count": "3",
        "flagged_neighbors": "1",
        "community_size": "4",
        "device_id": "dev-1",
        "node_labels": '["Person"]',
        "edge_timestamps": "[]",
    }
    defaults.update(kw)
    return defaults


class TestDeviceIndexModule(unittest.IsolatedAsyncioTestCase):
    async def test_module_exports_api(self) -> None:
        from graph_service import device_index

        for fn in (
            "ensure_device_index_table",
            "upsert_device_index",
            "delete_device_index",
            "count_shared_device",
        ):
            self.assertTrue(hasattr(device_index, fn), fn)

    async def test_count_excludes_self_and_empty_device(self) -> None:
        from graph_service import device_index

        conn = _Conn(fetchval=4)
        with (
            patch.object(device_index, "ensure_device_index_table", AsyncMock()),
            patch.object(device_index, "_acquire", AsyncMock(return_value=_Pool(conn))),
        ):
            n = await device_index.count_shared_device("t1", "dev-1", "u1")
        self.assertEqual(n, 4)  # fetchval is the post-exclusion count
        sql = conn.fetchval.await_args.args[0]
        self.assertIn("tenant_id = $1", sql)
        self.assertIn("device_id = $2", sql)
        self.assertIn("external_id <> $3", sql)

    async def test_count_empty_device_returns_zero_without_query(self) -> None:
        from graph_service import device_index

        with (
            patch.object(device_index, "ensure_device_index_table", AsyncMock()) as ens,
            patch.object(device_index, "_acquire", AsyncMock()) as acq,
        ):
            n = await device_index.count_shared_device("t1", "", "u1")
        self.assertEqual(n, 0)
        acq.assert_not_awaited()
        ens.assert_not_awaited()


class TestUpsertMaintainsIndex(unittest.IsolatedAsyncioTestCase):
    async def test_upsert_entity_writes_device_index_fail_soft(self) -> None:
        import graph_service.graph_runtime as rt

        store = types.SimpleNamespace(upsert_entity=AsyncMock(return_value="gid-1"))
        with (
            patch.object(rt, "_store", lambda: store),
            patch("graph_service.search_keys.upsert_search_keys", AsyncMock()),
            patch("graph_service.device_index.upsert_device_index", AsyncMock()) as dev_up,
        ):
            await rt.upsert_entity("t1", "Person", "u1", {"device_id": "dev-1"}, tags=["x"])
        dev_up.assert_awaited_once_with("t1", "dev-1", "u1")

    async def test_upsert_without_device_id_skips_index(self) -> None:
        import graph_service.graph_runtime as rt

        store = types.SimpleNamespace(upsert_entity=AsyncMock(return_value="gid-1"))
        with (
            patch.object(rt, "_store", lambda: store),
            patch("graph_service.search_keys.upsert_search_keys", AsyncMock()),
            patch("graph_service.device_index.upsert_device_index", AsyncMock()) as dev_up,
        ):
            await rt.upsert_entity("t1", "Person", "u2", {"name": "n"}, tags=[])
        dev_up.assert_not_awaited()

    async def test_index_failure_does_not_break_upsert(self) -> None:
        import graph_service.graph_runtime as rt

        store = types.SimpleNamespace(upsert_entity=AsyncMock(return_value="gid-1"))
        with (
            patch.object(rt, "_store", lambda: store),
            patch("graph_service.search_keys.upsert_search_keys", AsyncMock()),
            patch(
                "graph_service.device_index.upsert_device_index",
                AsyncMock(side_effect=RuntimeError("pg down")),
            ),
        ):
            gid = await rt.upsert_entity("t1", "Person", "u3", {"device_id": "d"}, tags=[])
        self.assertEqual(gid, "gid-1")


class TestComputeUsesIndex(unittest.IsolatedAsyncioTestCase):
    async def test_compute_reads_shared_devices_from_index(self) -> None:
        from graph_service import algorithms_age

        conn = _Conn(fetchval=2)
        conn.fetchrow = AsyncMock(return_value=_row())

        @asynccontextmanager
        async def _fake_acquire():
            yield conn

        with (
            patch.object(algorithms_age, "_acquire", _fake_acquire),
            patch.object(algorithms_age, "load_peer_p90_for_label", AsyncMock(return_value=5)),
            patch(
                "graph_service.device_index.count_shared_device", AsyncMock(return_value=3)
            ) as cnt,
        ):
            payload = await algorithms_age.compute_entity_risk("t1", "u1")
        cnt.assert_awaited_once_with("t1", "dev-1", "u1")
        self.assertIn("shared_devices:3", payload["risk_factors"])
        # the O(N) tenant scan must be gone from the cypher
        sql = algorithms_age.entity_risk_sql(3)
        self.assertNotIn("OPTIONAL MATCH (other)", sql)

    async def test_compute_without_device_reads_none(self) -> None:
        from graph_service import algorithms_age

        conn = _Conn(fetchval=0)
        conn.fetchrow = AsyncMock(
            return_value=_row(tags="[]", device_id="null", node_labels='["Person"]')
        )

        @asynccontextmanager
        async def _fake_acquire():
            yield conn

        with (
            patch.object(algorithms_age, "_acquire", _fake_acquire),
            patch.object(algorithms_age, "load_peer_p90_for_label", AsyncMock(return_value=None)),
            patch(
                "graph_service.device_index.count_shared_device", AsyncMock(return_value=0)
            ) as cnt,
        ):
            payload = await algorithms_age.compute_entity_risk("t1", "u1")
        cnt.assert_awaited_once_with(
            "t1", None, "u1"
        )  # empty device → still called with None; returns 0 fast


class TestDeleteSweepsIndex(unittest.IsolatedAsyncioTestCase):
    async def test_delete_entity_removes_device_index_rows(self) -> None:
        import graph_service.main as m

        with (
            patch.object(m, "query_subgraph", AsyncMock(return_value=_SUBGRAPH)),
            patch.object(m, "delete_entity", AsyncMock()),
            patch.object(m, "query_subgraph", AsyncMock(return_value=_SUBGRAPH)),
            patch("graph_service.search_keys.delete_search_keys", AsyncMock()),
            patch("graph_service.device_index.delete_device_index", AsyncMock()) as dev_del,
        ):
            from fastapi.testclient import TestClient

            with TestClient(m.app) as client:
                r = client.delete("/v1/entities/u1?tenant_id=t1")
        self.assertEqual(r.status_code, 200)
        dev_del.assert_awaited_once_with("t1", "u1")


if __name__ == "__main__":
    unittest.main()
