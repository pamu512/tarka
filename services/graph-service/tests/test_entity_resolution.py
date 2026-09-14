"""F3: persisted entity resolution.

``resolve_entity_candidates`` turns shared-attribute groups (existing transient
analytics) into resolution candidates; ``resolve_entities`` persists each
confirmed merge as a mutual ``ALIAS_OF`` edge with the F1 provenance envelope
plus a resolution ``strategy`` marker. Every write goes through
``graph_runtime.create_link``, so tenant schema, sanitizers, and the provenance
envelope all apply — no bespoke Cypher here.
"""

from __future__ import annotations

import os
import unittest
from unittest.mock import AsyncMock

os.environ.setdefault("GRAPH_BACKEND", "age")
os.environ.setdefault("ALLOW_INSECURE_NO_AUTH", "true")
os.environ.pop("API_KEYS", None)


class TestResolutionCandidates(unittest.TestCase):
    def test_candidates_from_shared_attribute_groups(self) -> None:
        import asyncio
        from unittest import mock

        from graph_service.entity_resolution import resolve_entity_candidates

        groups = [
            {"attribute": "device_id", "shared_value": "d-1", "entity_ids": ["u1", "u2"], "group_size": 2},
            {"attribute": "device_id", "shared_value": "d-2", "entity_ids": ["u2"], "group_size": 1},
            {"attribute": "email", "shared_value": "e@x", "entity_ids": ["u1", "u3"], "group_size": 2},
        ]

        async def _run() -> None:
            with mock.patch(
                "graph_service.entity_resolution.find_shared_attributes",
                new=AsyncMock(return_value=groups),
            ):
                out = await resolve_entity_candidates("acme")
            pairs = {(c["from_id"], c["to_id"], c["attribute"]) for c in out["candidates"]}
            self.assertIn(("u1", "u2", "device_id"), pairs)
            self.assertIn(("u1", "u3", "email"), pairs)
            self.assertNotIn(("u2", "u2", "device_id"), pairs)
            self.assertTrue(all(c["group_size"] >= 2 for c in out["candidates"]))
            self.assertEqual(out["tenant_id"], "acme")

        asyncio.run(_run())

    def test_candidates_require_min_shared(self) -> None:
        import asyncio
        from unittest import mock

        from graph_service.entity_resolution import resolve_entity_candidates

        async def _run() -> None:
            with mock.patch(
                "graph_service.entity_resolution.find_shared_attributes",
                new=AsyncMock(return_value=[]),
            ) as finder:
                out = await resolve_entity_candidates("acme", attribute="email", min_shared=3)
            finder.assert_awaited_once_with("acme", "email", 3)
            self.assertEqual(out["candidates"], [])

        asyncio.run(_run())


class TestResolveEntities(unittest.TestCase):
    def test_merge_persists_alias_of_with_provenance(self) -> None:
        import asyncio

        from graph_service.entity_resolution import resolve_entities

        links: list[tuple] = []

        async def _capture(tenant_id, from_id, to_id, relationship, properties):
            links.append((tenant_id, from_id, to_id, relationship, properties))

        async def _run() -> None:
            await resolve_entities(
                "acme",
                [
                    {
                        "from_id": "u1",
                        "to_id": "u2",
                        "attribute": "device_id",
                        "shared_value": "d-1",
                        "strategy": "shared_attribute",
                    },
                    {
                        "from_id": "u3",
                        "to_id": "u4",
                        "attribute": "email",
                        "shared_value": "e@x",
                        "strategy": "shared_attribute",
                    },
                ],
                create_link=_capture,
            )
            self.assertEqual(len(links), 2)
            for tid, a, b, rel, props in links:
                self.assertEqual(tid, "acme")
                self.assertEqual(rel, "ALIAS_OF")
                self.assertTrue(props["ingested_at"])
                self.assertEqual(props["resolution_strategy"], "shared_attribute")
                self.assertEqual(props["resolution_attribute"], props.get("resolution_attribute"))
            (a1) = {links[0][1], links[0][2]}
            self.assertEqual(a1, {"u1", "u2"})

        asyncio.run(_run())

    def test_merge_rejects_self_loop(self) -> None:
        import asyncio

        from graph_service.entity_resolution import resolve_entities

        async def _run() -> None:
            with self.assertRaises(ValueError):
                await resolve_entities(
                    "acme",
                    [{"from_id": "u1", "to_id": "u1", "attribute": "device_id",
                      "shared_value": "d", "strategy": "shared_attribute"}],
                    create_link=AsyncMock(),
                )

        asyncio.run(_run())

    def test_merge_is_idempotent_per_pair(self) -> None:
        import asyncio

        from graph_service.entity_resolution import resolve_entities

        calls: list[tuple] = []

        async def _capture(tenant_id, from_id, to_id, relationship, properties):
            calls.append((from_id, to_id, relationship))

        async def _run() -> None:
            candidates = [
                {"from_id": "u1", "to_id": "u2", "attribute": "device_id",
                 "shared_value": "d-1", "strategy": "shared_attribute"},
                {"from_id": "u2", "to_id": "u1", "attribute": "device_id",
                 "shared_value": "d-1", "strategy": "shared_attribute"},
            ]
            await resolve_entities("acme", candidates, create_link=_capture)
            self.assertEqual(len(calls), 1, "u1~u2 and u2~u1 are the same pair")

        asyncio.run(_run())


if __name__ == "__main__":
    unittest.main()
