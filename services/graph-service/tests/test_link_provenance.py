"""F1: edge-level provenance envelope, enforced at the link-write boundary.

Contract: every created edge carries
- ``ingested_at`` — ingestion clock (RFC3339, stamped exactly once at create),
- ``observed_at`` — event clock; caller value kept ONLY if it parses as a timestamp,
  otherwise repaired to now (placeholders like \"evaluate\" must not survive),
- ``confidence`` — caller value clamped to [0, 1] when present,
- ``decision_id`` / ``trace_id`` — caller passthrough, never dropped.
Match-updates never rewrite the ingestion clock.
"""

from __future__ import annotations

import os
import unittest
from datetime import datetime, timedelta, timezone

os.environ.setdefault("GRAPH_BACKEND", "age")
os.environ.setdefault("ALLOW_INSECURE_NO_AUTH", "true")
os.environ.pop("API_KEYS", None)


def _is_rfc3339(value: object) -> bool:
    if not isinstance(value, str) or not value:
        return False
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return True


class TestProvenanceHelpers(unittest.TestCase):
    def test_create_stamps_ingested_at_once(self) -> None:
        from graph_service.entity_risk_score import link_props_for_create

        props = link_props_for_create({"trace_id": "t-1"})
        self.assertTrue(_is_rfc3339(props["ingested_at"]))
        self.assertTrue(_is_rfc3339(props["observed_at"]))
        self.assertEqual(props["trace_id"], "t-1")

    def test_create_repairs_placeholder_observed_at(self) -> None:
        from graph_service.entity_risk_score import link_props_for_create

        before = datetime.now(timezone.utc) - timedelta(seconds=5)
        props = link_props_for_create({"observed_at": "evaluate", "decision_id": "d-9"})
        self.assertTrue(_is_rfc3339(props["observed_at"]), "placeholder must be repaired")
        self.assertTrue(_is_rfc3339(props["decision_id"] + "") or True)
        self.assertEqual(props["decision_id"], "d-9")
        parsed = datetime.fromisoformat(props["observed_at"].replace("Z", "+00:00"))
        self.assertGreaterEqual(parsed, before)

    def test_create_keeps_valid_observed_at(self) -> None:
        from graph_service.entity_risk_score import link_props_for_create

        kept = "2026-01-02T03:04:05+00:00"
        props = link_props_for_create({"observed_at": kept})
        self.assertEqual(props["observed_at"], kept)
        self.assertTrue(_is_rfc3339(props["ingested_at"]))

    def test_confidence_clamped_to_unit_interval(self) -> None:
        from graph_service.entity_risk_score import link_props_for_create

        self.assertEqual(link_props_for_create({"confidence": 7})["confidence"], 1.0)
        self.assertEqual(link_props_for_create({"confidence": -3})["confidence"], 0.0)
        self.assertEqual(link_props_for_create({"confidence": 0.42})["confidence"], 0.42)
        self.assertNotIn("confidence", link_props_for_create({"trace_id": "t"}))

    def test_match_update_never_rewrites_ingestion_clock(self) -> None:
        from graph_service.entity_risk_score import link_props_for_match

        props = link_props_for_match({"risk_score": 9})
        self.assertEqual(props, {"risk_score": 9})
        self.assertNotIn("ingested_at", props)


class TestLinksEndpointProvenance(unittest.TestCase):
    def test_http_links_normalizes_provenance_props(self) -> None:
        import asyncio
        from unittest import mock
        from unittest.mock import AsyncMock

        from fastapi.testclient import TestClient

        from graph_service import age_client
        from graph_service.config import settings as gs_settings
        from graph_service.main import app

        captured: dict = {}

        async def _capture(*args, **kwargs):
            captured["args"] = args
            captured["kwargs"] = kwargs

        async def _run() -> None:
            saved = gs_settings.graph_backend
            gs_settings.graph_backend = "age"
            try:
                with mock.patch.object(age_client, "create_link", new=_capture):
                    with TestClient(app) as client:
                        r = client.post(
                            "/v1/links",
                            json={
                                "tenant_id": "acme",
                                "from_external_id": "a",
                                "to_external_id": "b",
                                "relationship": "USED",
                                "properties": {
                                    "observed_at": "evaluate",
                                    "confidence": 7,
                                    "decision_id": "d-1",
                                },
                            },
                        )
                self.assertEqual(r.status_code, 200, r.text)
            finally:
                gs_settings.graph_backend = saved

        asyncio.run(_run())
        props = (captured.get("kwargs") or {}).get("properties") or captured["args"][4]
        self.assertTrue(_is_rfc3339(props["observed_at"]))
        self.assertTrue(_is_rfc3339(props["ingested_at"]))
        self.assertEqual(props["confidence"], 1.0)
        self.assertEqual(props["decision_id"], "d-1")
