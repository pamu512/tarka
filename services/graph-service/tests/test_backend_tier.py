"""D6-1/2: AGE is the core graph engine; pads must be opt-in and declared.

Doctrine: Apache AGE is the engine the stack is built around. neo4j/janusgraph
are porting pads for desks bringing existing stores — a degraded experience that
must be DECLARED (config default = age; /v1/health carries backend + tier +
degraded capabilities; startup warns loudly on a pad).
"""

from __future__ import annotations

import os
import unittest


class TestCoreDefault(unittest.TestCase):
    def test_default_backend_is_age(self) -> None:
        """Fresh settings with no env must select the core engine."""
        import importlib

        from graph_service import config as gs_config

        saved = os.environ.pop("GRAPH_BACKEND", None)
        try:
            fresh = importlib.import_module("graph_service.config")
            importlib.reload(fresh)
            self.assertEqual(fresh.Settings().graph_backend, "age")
        finally:
            if saved is not None:
                os.environ["GRAPH_BACKEND"] = saved
            importlib.reload(gs_config)


class TestTierDeclaration(unittest.TestCase):
    def test_age_is_core_with_no_degradations(self) -> None:
        from graph_service.main import _experience_tier

        tier = _experience_tier("age")
        self.assertEqual(tier["experience_tier"], "core")
        self.assertEqual(tier["degraded_capabilities"], [])

    def test_porting_pads_declare_degradations(self) -> None:
        from graph_service.main import _experience_tier

        for pad in ("janusgraph", "neo4j"):
            tier = _experience_tier(pad)
            self.assertEqual(tier["experience_tier"], "porting", pad)
            self.assertTrue(tier["degraded_capabilities"], pad)

    def test_unknown_backend_fails_closed(self) -> None:
        from graph_service.main import _experience_tier

        with self.assertRaises(ValueError):
            _experience_tier("bolt-on-mystery")

    def test_health_declares_backend_and_tier(self) -> None:
        os.environ.setdefault("ALLOW_INSECURE_NO_AUTH", "true")
        os.environ.pop("API_KEYS", None)
        from fastapi.testclient import TestClient

        from graph_service.main import app, settings

        saved = settings.graph_backend
        settings.graph_backend = "janusgraph"
        try:
            with TestClient(app) as client:
                r = client.get("/v1/health")
            self.assertEqual(r.status_code, 200)
            block = r.json()["graph_backend"]
            self.assertEqual(block["backend"], "janusgraph")
            self.assertEqual(block["experience_tier"], "porting")
            self.assertTrue(block["degraded_capabilities"])
        finally:
            settings.graph_backend = saved
