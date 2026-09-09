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
        self.assertIn("docs/contracts/pack-promote-export-v1.md", lock)
        self.assertIn("contract-gated", lock.lower())
        self.assertIn("emit-only", lock.lower())
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
            "docs/contracts/vendor-score-slot-v1.md",
            "docs/contracts/pack-promote-export-v1.md",
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

    def test_pack_promote_export_contract_honesty(self) -> None:
        text = (ROOT / "docs/contracts/pack-promote-export-v1.md").read_text(encoding="utf-8")
        lowered = text.lower()
        self.assertIn("tarka.pack_promote_export/v1", text)
        self.assertIn("Event name: `tarka.pack_promote_export/v1`", text)
        self.assertIn("desk promote", lowered)
        self.assertIn("backup", lowered)
        self.assertNotIn("gitlab-grade", lowered)
        self.assertNotIn("git required to promote", lowered)
        self.assertNotIn("git is required to promote", lowered)
        self.assertNotIn("open-source", lowered)
        self.assertNotIn("open source", lowered)
        emitter = (
            ROOT / "services/decision-api/src/decision_api/promote_gitops.py"
        ).read_text(encoding="utf-8")
        self.assertIn('SCHEMA_ID = "tarka.pack_promote_export/v1"', emitter)

    def test_claim_lock_tip_table_pack_export_backup_never_go_live(self) -> None:
        lock = (ROOT / "docs/compliance/CLAIM_LOCK.md").read_text(encoding="utf-8")
        start = lock.index("## Tip claims")
        table = lock[start:]
        end = table.find("\n**Provision")
        if end != -1:
            table = table[:end]
        row = next(
            line
            for line in table.splitlines()
            if "tarka.pack_promote_export/v1" in line and line.startswith("|")
        )
        cols = [c.strip() for c in row.strip().strip("|").split("|")]
        self.assertEqual(len(cols), 2)
        true_side, must_not = cols
        true_l = true_side.lower()
        must_l = must_not.lower()
        self.assertIn("desk", true_l)
        self.assertIn("sot", true_l)
        self.assertIn("backup", true_l)
        self.assertIn("never", true_l)
        self.assertIn("go-live gate", true_l)
        self.assertTrue(true_side.strip() and must_not.strip())
        self.assertIn("git merge", must_l)
        self.assertIn("go-live gate", must_l)
        self.assertIn("promote authority", must_l)


if __name__ == "__main__":
    raise SystemExit(unittest.main())
