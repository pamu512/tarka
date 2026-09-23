"""R3 follow-up 2: persist_entity_risk_many batches per-entity SETs.

refresh_tenant already runs computes concurrently (sem 4); the remaining
serial cost is one SET round-trip per entity inside persist. A batched
variant packs N entities into one cypher UNWIND statement (single
round-trip) with identical per-entity write semantics.
"""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, patch

import graph_service.entity_risk_writeback as wb


def _found(eid: str, label: str = "Person") -> dict:
    return {
        "entity_id": eid,
        "primary_label": label,
        "risk_score": 0.5,
        "risk_factors": ["f"],
        "relation_count": 2,
        "relation_growth_1h": 0,
        "relation_growth_24h": 0,
    }


class TestPersistMany(unittest.IsolatedAsyncioTestCase):
    async def test_batch_packs_all_entities_into_one_execute(self):
        payloads = {f"e{i}": _found(f"e{i}") for i in range(5)}

        async def fake_scan(tid, limit):
            return list(payloads), False

        async def fake_stats(*a, **k):
            return None

        with (
            patch("graph_service.entity_risk_writeback.scan_tenant_entity_ids", fake_scan),
            patch(
                "graph_service.entity_risk_writeback.compute_entity_risk",
                AsyncMock(side_effect=lambda t, e: _found(e)),
            ),
            patch(
                "graph_service.entity_risk_writeback.set_entity_risk_properties_many",
                AsyncMock(return_value=5),
            ) as many,
            patch("graph_service.entity_risk_writeback.persist_entity_risk", AsyncMock()) as one,
            patch("graph_service.entity_risk_writeback.upsert_graph_risk_stats", fake_stats),
        ):
            out = await wb.refresh_tenant("t1", limit=100)
        self.assertEqual(out, {"updated": 5, "skipped": 0, "truncated": False})
        self.assertEqual(many.await_count, 1)
        one.assert_not_called()
        batch = many.await_args.args[1]
        self.assertEqual(len(batch), 5)

    async def test_batch_statement_is_single_unwind_round_trip(self):
        from graph_service.age_client import set_entity_risk_properties_many

        executed: list[tuple] = []

        class _Conn:
            async def execute(self, q, *a):
                executed.append((q, a))
                return "OK"

        class _Pool:
            def acquire(self):
                return self

            async def __aenter__(self):
                return _Conn()

            async def __aexit__(self, *_a):
                return False

        async def _pool():
            return _Pool()

        import graph_service.age_client as ac

        with patch.object(ac, "get_pool", _pool):
            await ac.set_entity_risk_properties_many(
                "t1",
                [
                    {"entity_id": "e1", "risk_score": 10.0, "risk_factors": ["a"]},
                    {"entity_id": "e2", "risk_score": 20.0, "risk_factors": []},
                ],
            )
        self.assertEqual(len(executed), 1)
        q = executed[0][0]
        self.assertIn("UNWIND", q)
        self.assertIn("risk_score", q)
        # params carry the batch as ONE json argument
        self.assertEqual(len(executed[0][1]), 1)

    async def test_batch_skips_not_found_payloads(self):
        from graph_service.age_client import set_entity_risk_properties_many
        from graph_service.entity_risk_score import entity_not_found_payload

        calls: list = []

        class _Conn:
            async def execute(self, q, *a):
                calls.append(q)
                return "OK"

        class _Pool:
            def acquire(self):
                return self

            async def __aenter__(self):
                return _Conn()

            async def __aexit__(self, *_a):
                return False

        import graph_service.age_client as ac

        with patch.object(ac, "get_pool", _pool := _get_pool(_Conn())):
            await ac.set_entity_risk_properties_many(
                "t1",
                [
                    entity_not_found_payload("gone", None, None, 3),
                    _found("here"),
                ],
            )
        self.assertEqual(len(calls), 1)  # one batch, filtered to found payloads


def _get_pool(conn):
    class _P:
        def acquire(self):
            return self

        async def __aenter__(self):
            return conn

        async def __aexit__(self, *_a):
            return False

    async def maker():
        return _P()

    return maker


if __name__ == "__main__":
    unittest.main()
