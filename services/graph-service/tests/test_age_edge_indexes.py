"""Age edge indexes: start_id/end_id per edge label (the 36s->15ms fix).

AGE creates per-label edge tables without join indexes; every (n)-[r]-(nb)
walk degrades to a nested-loop cross product (measured: 7.2M rows removed,
12-36s per compute on a 7.5k-node lite graph). Creating btree indexes on
start_id/end_id per edge label restores index joins (measured: 15ms).
"""

from __future__ import annotations

import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, call


def _load():
    from graph_service import age_client

    return age_client


class TestAgeEdgeIndexes(unittest.IsolatedAsyncioTestCase):
    async def test_ensure_creates_index_per_edge_label(self):
        ac = _load()
        conn = MagicMock()
        conn.execute = AsyncMock()
        pool = MagicMock()
        pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
        pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)

        async def _fetch_labels(q, *a):
            if "ag_graph" in q:
                return [{"graph": 12345}]
            if "ag_label" in q:
                return [{"name": "KNOWS"}, {"name": "USED_DEVICE"}]
            return []

        conn.fetch = AsyncMock(side_effect=_fetch_labels)
        conn.fetchrow = AsyncMock(return_value={"graph": 12345})
        ac.get_pool = AsyncMock(return_value=pool)

        await ac.ensure_age_edge_indexes()

        executed = [
            c.args[0] for c in conn.execute.await_args_list if "CREATE INDEX" in str(c.args[0])
        ]
        names = {str(e) for e in executed}
        self.assertTrue(any("KNOWS" in n and "start_id" in n for n in names), names)
        self.assertTrue(any("KNOWS" in n and "end_id" in n for n in names))
        self.assertTrue(any("USED_DEVICE" in n and "start_id" in n for n in names))
        self.assertTrue(any("USED_DEVICE" in n and "end_id" in n for n in names))

    async def test_ensure_is_fail_soft_and_once_only(self):
        ac = _load()
        # Failure must not raise and must allow a later retry.
        conn = MagicMock()
        conn.execute = AsyncMock(side_effect=RuntimeError("pg down"))
        conn.fetch = AsyncMock(return_value=[{"name": "KNOWS"}])
        pool = MagicMock()
        pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
        pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)
        ac.get_pool = AsyncMock(return_value=pool)
        await ac.ensure_age_edge_indexes()  # no raise

        # Success sets the once-guard: a second call must not re-acquire.
        conn2 = MagicMock()
        conn2.execute = AsyncMock()
        conn2.fetch = AsyncMock(return_value=[{"name": "KNOWS"}])
        pool2 = MagicMock()
        pool2.acquire.return_value.__aenter__ = AsyncMock(return_value=conn2)
        pool2.acquire.return_value.__aexit__ = AsyncMock(return_value=False)
        ac.get_pool = AsyncMock(return_value=pool2)
        await ac.ensure_age_edge_indexes()  # retry succeeds
        ac.get_pool = AsyncMock(side_effect=AssertionError("second acquire"))
        await ac.ensure_age_edge_indexes()  # short-circuits

    async def test_identifier_quoting_rejects_weird_labels(self):
        ac = _load()
        self.assertEqual(ac._quote_age_ident("KNOWS"), '"KNOWS"')
        with self.assertRaises(ValueError):
            ac._quote_age_ident('BAD"LABEL')


if __name__ == "__main__":
    unittest.main()
