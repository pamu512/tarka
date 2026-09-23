"""R3 follow-up: refresh_tenant bounded concurrency.

Serial compute+SET per entity costs 2 AGE round-trips each (~200ms); a
tenant of N is 2N serial round-trips. Bounded asyncio concurrency (default
4, pool max 10) keeps per-entity error isolation and the exact response
shape while cutting wall time.
"""

from __future__ import annotations

import asyncio
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


class TestRefreshTenantConcurrency(unittest.IsolatedAsyncioTestCase):
    async def test_all_entities_refreshed_with_same_shape(self):
        ids = [f"e{i}" for i in range(9)]

        async def fake_scan(tid, limit):
            return list(ids), False

        async def fake_stats(*a, **k):
            return None

        with (
            patch("graph_service.entity_risk_writeback.scan_tenant_entity_ids", fake_scan),
            patch(
                "graph_service.entity_risk_writeback.compute_entity_risk",
                AsyncMock(side_effect=lambda t, e: _found(e)),
            ),
            patch(
                "graph_service.entity_risk_writeback.set_entity_risk_properties", AsyncMock()
            ) as setter,
            patch("graph_service.entity_risk_writeback.upsert_graph_risk_stats", fake_stats),
        ):
            out = await wb.refresh_tenant("t1", limit=100)
        self.assertEqual(out, {"updated": 9, "skipped": 0, "truncated": False})
        self.assertEqual(setter.await_count, 9)

    async def test_failures_are_isolated_and_counted_skipped(self):
        ids = ["ok1", "bad", "ok2"]

        async def fake_scan(tid, limit):
            return list(ids), False

        calls = {"n": 0}

        async def compute(t, e):
            calls["n"] += 1
            if e == "bad":
                raise RuntimeError("boom")
            return _found(e)

        async def fake_stats(*a, **k):
            return None

        with (
            patch("graph_service.entity_risk_writeback.scan_tenant_entity_ids", fake_scan),
            patch("graph_service.entity_risk_writeback.compute_entity_risk", compute),
            patch(
                "graph_service.entity_risk_writeback.set_entity_risk_properties", AsyncMock()
            ) as setter,
            patch("graph_service.entity_risk_writeback.upsert_graph_risk_stats", fake_stats),
        ):
            out = await wb.refresh_tenant("t1", limit=100)
        self.assertEqual(out, {"updated": 2, "skipped": 1, "truncated": False})
        self.assertEqual(setter.await_count, 2)

    async def test_concurrency_is_bounded_by_semaphore(self):
        ids = [f"e{i}" for i in range(12)]
        inflight = 0
        peak = 0

        async def compute(t, e):
            nonlocal inflight, peak
            inflight += 1
            peak = max(peak, inflight)
            await asyncio.sleep(0.01)
            inflight -= 1
            return _found(e)

        async def fake_scan(tid, limit):
            return list(ids), False

        async def fake_stats(*a, **k):
            return None

        with (
            patch("graph_service.entity_risk_writeback.scan_tenant_entity_ids", fake_scan),
            patch("graph_service.entity_risk_writeback.compute_entity_risk", compute),
            patch("graph_service.entity_risk_writeback.set_entity_risk_properties", AsyncMock()),
            patch("graph_service.entity_risk_writeback.upsert_graph_risk_stats", fake_stats),
        ):
            out = await wb.refresh_tenant("t1", limit=100, concurrency=3)
        self.assertEqual(out["updated"], 12)
        self.assertLessEqual(peak, 3)
        self.assertGreater(peak, 1)  # actually parallel, not serial

    async def test_label_p90_still_computed_after_parallel_refresh(self):
        ids = [f"e{i}" for i in range(5)]

        async def fake_scan(tid, limit):
            return list(ids), False

        stats_calls: list = []

        async def fake_stats(tid, p90_map, ts):
            stats_calls.append((tid, p90_map))

        with (
            patch("graph_service.entity_risk_writeback.scan_tenant_entity_ids", fake_scan),
            patch(
                "graph_service.entity_risk_writeback.compute_entity_risk",
                AsyncMock(side_effect=lambda t, e: _found(e)),
            ),
            patch("graph_service.entity_risk_writeback.set_entity_risk_properties", AsyncMock()),
            patch("graph_service.entity_risk_writeback.upsert_graph_risk_stats", fake_stats),
        ):
            out = await wb.refresh_tenant("t1", limit=100)
        self.assertEqual(out["updated"], 5)
        self.assertEqual(len(stats_calls), 1)
        self.assertIn("Person", stats_calls[0][1])


if __name__ == "__main__":
    unittest.main()
