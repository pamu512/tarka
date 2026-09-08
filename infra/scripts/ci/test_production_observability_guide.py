#!/usr/bin/env python3
"""Thin production-observability guide is present and scoped (not a full Observability SKU)."""

from __future__ import annotations

import unittest
from pathlib import Path

_REPO = Path(__file__).resolve().parents[3]
_GUIDE = _REPO / "docs" / "docs" / "guides" / "production-observability.md"


class TestProductionObservabilityGuide(unittest.TestCase):
    def test_guide_covers_scrape_and_evaluate_alerts(self) -> None:
        self.assertTrue(_GUIDE.is_file(), f"missing {_GUIDE.relative_to(_REPO)}")
        text = _GUIDE.read_text(encoding="utf-8")
        self.assertIn("ServiceMonitor", text)
        self.assertIn("NetworkPolicy", text)
        self.assertIn("/metrics", text)
        self.assertIn("5xx", text)
        self.assertIn("latency", text.lower())
        self.assertIn("/v1/decisions/evaluate", text)
        self.assertIn("global.networkPolicy.enabled=false", text)
        self.assertIn("global.serviceMonitor.enabled=false", text)
        self.assertIn("lite-on-k8s", text)
        self.assertNotIn("Istio required", text)
        lowered = text.lower()
        self.assertTrue("not a full" in lowered or "not an observability sku" in lowered)


if __name__ == "__main__":
    raise SystemExit(unittest.main())
