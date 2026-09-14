#!/usr/bin/env python3
"""Compose guard (D6): AGE is the core graph backend; janusgraph is a pad.

- full compose's graph-service must default GRAPH_BACKEND to age (core demo)
- graph-service must not hard-depend on the janusgraph JVM (pad boots opt-in)
- the janusgraph pad service itself must still exist
- the explicit porting overlay must keep its janusgraph default
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

_REPO = Path(__file__).resolve().parents[3]
_COMPOSE = _REPO / "infra/deploy/docker-compose.yml"
_OVERLAY = _REPO / "infra/deploy/docker-compose.graph-env.yml"


def _service_block(text: str, service: str) -> str:
    m = re.search(rf"(?ms)^  {re.escape(service)}:\n(.*?)(?=^  \S|\Z)", text)
    assert m, f"service {service} missing from compose"
    return m.group(0)


class TestComposeGraphCore(unittest.TestCase):
    def setUp(self) -> None:
        self.text = _COMPOSE.read_text()
        self.gs = _service_block(self.text, "graph-service")
        self.janus = _service_block(self.text, "janusgraph")

    def test_full_compose_defaults_to_age(self) -> None:
        self.assertRegex(self.gs, r"GRAPH_BACKEND: \$\{GRAPH_BACKEND:-age\}")

    def test_graph_service_does_not_depend_on_janus(self) -> None:
        self.assertNotIn("janusgraph:", self.gs.split("depends_on:")[-1])

    def test_graph_service_targets_age_database(self) -> None:
        self.assertIn("AGE_DATABASE_URL:", self.gs)

    def test_janus_pad_still_exists_for_opt_in(self) -> None:
        self.assertIn("janusgraph:1.0.0", self.janus)

    def test_porting_overlay_keeps_janus_default(self) -> None:
        overlay = _OVERLAY.read_text()
        self.assertIn("GRAPH_BACKEND: ${GRAPH_BACKEND:-janusgraph}", overlay)


if __name__ == "__main__":
    unittest.main()
