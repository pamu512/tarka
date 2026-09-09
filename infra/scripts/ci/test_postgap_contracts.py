#!/usr/bin/env python3
"""Post-gap contract spine (W0). Run: python3 infra/scripts/ci/test_postgap_contracts.py"""

from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


class TestPostgapContractSpine(unittest.TestCase):
    def test_enforcement_contract_exists(self) -> None:
        path = ROOT / "docs/contracts/enforcement-v1.md"
        self.assertTrue(path.is_file(), path)
        text = path.read_text(encoding="utf-8")
        self.assertIn("emit_only", text)
        self.assertIn("handoff", text)
        self.assertIn("decision.emitted", text)
        self.assertIn("x-tarka-signature", text.lower())
        self.assertIn("hmac-sha256", text.lower())
        self.assertIn("empty url", text.lower())

    def test_label_join_contract_exists(self) -> None:
        path = ROOT / "docs/contracts/label-join-v1.md"
        self.assertTrue(path.is_file(), path)
        text = path.read_text(encoding="utf-8")
        self.assertIn("evaluation_token", text)
        self.assertIn("label_kind", text)

    def test_claim_lock_points_at_contracts(self) -> None:
        lock = (ROOT / "docs/compliance/CLAIM_LOCK.md").read_text(encoding="utf-8")
        self.assertIn("docs/contracts/enforcement-v1.md", lock)
        self.assertIn("docs/contracts/label-join-v1.md", lock)
        self.assertIn("contract-gated", lock.lower())
        self.assertIn("emit-only", lock.lower())
        self.assertIn("x-tarka-signature", lock.lower())
        self.assertIn("hmac-sha256", lock.lower())
        self.assertIn("unsigned", lock.lower())
        self.assertIn("silent block in emit-only", lock.lower())
        self.assertIn("PackWhyStrip", lock)
        self.assertIn("pack-why", lock.lower())

    def test_late_label_docs_cite_join_contract(self) -> None:
        guide = (ROOT / "docs/docs/guides/gnn-label-loop.md").read_text(encoding="utf-8")
        self.assertIn("label-join-v1.md", guide)
        self.assertIn("evaluation_token", guide)

    def test_readme_enforcement_honesty(self) -> None:
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("emit-only", readme.lower())

    def test_later_contracts_exist(self) -> None:
        for rel in (
            "docs/contracts/bakeoff-metrics-v1.md",
            "docs/contracts/queue-seam-v1.md",
            "docs/contracts/warehouse-sink-v1.md",
            "docs/contracts/feature-store-posture-v1.md",
            "docs/contracts/graph-planes-v1.md",
            "docs/contracts/hunt-depth-v1.md",
            "docs/contracts/vendor-score-slot-v1.md",
        ):
            self.assertTrue((ROOT / rel).is_file(), rel)

    def test_bakeoff_pack_metrics_schema_named(self) -> None:
        text = (ROOT / "docs/contracts/bakeoff-metrics-v1.md").read_text(encoding="utf-8")
        for needle in (
            "pack_metrics",
            "pack_id",
            "rule_hit_rate",
            "shadow_divergence",
            "tarka.pack_metrics/v1",
            "null = unknown",
            "M2",
        ):
            self.assertIn(needle, text)
        lock = (ROOT / "docs/compliance/CLAIM_LOCK.md").read_text(encoding="utf-8")
        self.assertIn("pack_metrics", lock)


if __name__ == "__main__":
    raise SystemExit(unittest.main())
