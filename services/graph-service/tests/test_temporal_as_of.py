"""F2: bitemporal as-of reads over the subgraph.

Two clocks on every edge (since F1):
- ``ingested_at`` — transaction time (what the store knew)
- ``observed_at`` — valid time (when the event happened)

``apply_as_of(data, as_of=...)`` keeps only edges consistent with the asked
moment: ingested_at <= as_of (the edge existed) AND observed_at <= as_of (the
event had happened). Legacy edges without stamps are counted in
``unversioned_edges`` and kept (declared ambiguity, not silent loss).
"""

from __future__ import annotations

import os
import unittest
from datetime import datetime, timedelta, timezone

os.environ.setdefault("GRAPH_BACKEND", "age")
os.environ.setdefault("ALLOW_INSECURE_NO_AUTH", "true")
os.environ.pop("API_KEYS", None)


def _iso(dt: datetime) -> str:
    return dt.isoformat().replace("+00:00", "Z")


class TestAsOfFilter(unittest.TestCase):
    def _graph(self) -> dict:
        now = datetime.now(timezone.utc)
        return {
            "nodes": [{"id": "a"}, {"id": "b"}, {"id": "c"}],
            "edges": [
                {
                    "id": "e-old",
                    "type": "USED",
                    "startNode": "a",
                    "endNode": "b",
                    "properties": {
                        "ingested_at": _iso(now - timedelta(days=30)),
                        "observed_at": _iso(now - timedelta(days=31)),
                    },
                },
                {
                    "id": "e-new-ingest",
                    "type": "USED",
                    "startNode": "a",
                    "endNode": "c",
                    "properties": {
                        "ingested_at": _iso(now - timedelta(days=1)),
                        "observed_at": _iso(now - timedelta(days=40)),
                    },
                },
                {
                    "id": "e-future-event",
                    "type": "SEEN_AT",
                    "startNode": "b",
                    "endNode": "c",
                    "properties": {
                        "ingested_at": _iso(now - timedelta(days=30)),
                        "observed_at": _iso(now + timedelta(days=2)),
                    },
                },
                {
                    "id": "e-legacy",
                    "type": "USED",
                    "startNode": "c",
                    "endNode": "a",
                    "properties": {},
                },
            ],
        }

    def test_as_of_excludes_late_ingestion_and_future_events(self) -> None:
        from graph_service.temporal_filter import apply_as_of

        now = datetime.now(timezone.utc)
        week_ago = _iso(now - timedelta(days=7))
        out = apply_as_of(self._graph(), as_of=week_ago)
        ids = [e["id"] for e in out["edges"]]
        self.assertIn("e-old", ids)
        self.assertNotIn("e-new-ingest", ids, "edge not yet ingested must be invisible")
        self.assertNotIn("e-future-event", ids, "future-dated event must be invisible")
        self.assertIn("e-legacy", ids)
        self.assertEqual(out["unversioned_edges"], 1)
        self.assertEqual(out["as_of"], week_ago)

    def test_no_as_of_returns_graph_untouched(self) -> None:
        from graph_service.temporal_filter import apply_as_of

        graph = self._graph()
        out = apply_as_of(graph, as_of=None)
        self.assertEqual(len(out["edges"]), 4)
        self.assertNotIn("unversioned_edges", out)

    def test_bad_timestamp_is_422_not_500(self) -> None:
        import asyncio

        from fastapi.testclient import TestClient

        from graph_service.main import app

        async def _run() -> None:
            with TestClient(app) as client:
                r = client.get(
                    "/v1/subgraph",
                    params={"tenant_id": "acme", "entity_id": "x", "as_of": "evaluate"},
                )
            self.assertEqual(r.status_code, 422)

        asyncio.run(_run())

    def test_links_endpoint_accepts_as_of(self) -> None:
        import asyncio
        from datetime import timedelta
        from unittest import mock

        from fastapi.testclient import TestClient

        from graph_service import age_client
        from graph_service.config import settings as gs_settings
        from graph_service.main import app

        now = datetime.now(timezone.utc)
        graph = {
            "nodes": [{"id": "x"}, {"id": "b"}],
            "edges": [
                {
                    "id": "e-visible",
                    "type": "USED",
                    "startNode": "x",
                    "endNode": "b",
                    "from_id": "x",
                    "to_id": "b",
                    "properties": {
                        "ingested_at": _iso(now - timedelta(days=30)),
                        "observed_at": _iso(now - timedelta(days=30)),
                    },
                },
                {
                    "id": "e-late",
                    "type": "USED",
                    "startNode": "x",
                    "endNode": "b",
                    "from_id": "x",
                    "to_id": "b",
                    "properties": {
                        "ingested_at": _iso(now - timedelta(days=1)),
                        "observed_at": _iso(now - timedelta(days=30)),
                    },
                },
            ],
        }

        async def _capture(tenant_id, external_id, depth, **kwargs):
            return graph

        body: dict = {}

        async def _run() -> None:
            nonlocal body
            saved = gs_settings.graph_backend
            gs_settings.graph_backend = "age"
            try:
                with mock.patch.object(age_client, "query_subgraph", new=_capture):
                    with TestClient(app) as client:
                        r = client.get(
                            "/v1/entities/x/links",
                            params={
                                "tenant_id": "acme",
                                "as_of": _iso(now - timedelta(days=7)),
                            },
                        )
                self.assertEqual(r.status_code, 200, r.text)
                body = r.json()
            finally:
                gs_settings.graph_backend = saved

        asyncio.run(_run())
        self.assertEqual([e["id"] for e in body["edges"]], ["e-visible"])
        self.assertEqual(body["unversioned_edges"], 0)


if __name__ == "__main__":
    unittest.main()
