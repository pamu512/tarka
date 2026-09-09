#!/usr/bin/env python3
"""D7.1 AGE Hunt depth honesty contract. Run: python3 infra/scripts/ci/test_hunt_depth_contract.py"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]

SCHEMA_ID = "tarka.hunt_depth/v1"
SCHEMA_FIELDS = (
    "hunt_depth_max",
    "depth_requested",
    "depth_applied",
    "degrade_reason",
)

# New buyer rows / hunt-depth contract only. Must stay in Tarka terms.
FORBIDDEN = (
    re.compile(r"neo4j[- ]class", re.I),
    re.compile(r"\boss\b", re.I),
    re.compile(r"open[- ]source", re.I),
    re.compile(
        r"\b(sift|forter|riskified|feedzai|featurespace|unit21|sardine|datavisor)\b",
        re.I,
    ),
)


def _claim_lock_hunt_rows(lock: str) -> str:
    return "\n".join(
        line
        for line in lock.splitlines()
        if any(
            needle in line
            for needle in (
                "hunt-depth-v1",
                "hunt_depth",
                "Hunt depth",
                "AGE Hunt",
                "AGE depth-1",
                "Path B",
            )
        )
    )


class TestHuntDepthContract(unittest.TestCase):
    def test_schema_field_names_exist(self) -> None:
        path = ROOT / "docs/contracts/hunt-depth-v1.md"
        self.assertTrue(path.is_file(), path)
        text = path.read_text(encoding="utf-8")
        self.assertIn(SCHEMA_ID, text)
        for field in SCHEMA_FIELDS:
            self.assertIn(field, text)
        self.assertIn("GRAPH_SERVICE_URL", text)
        self.assertRegex(text, r"depth-1")
        self.assertRegex(text, r"(?i)empty `GRAPH_SERVICE_URL`.{0,80}\boff\b")
        self.assertNotRegex(text, r"later slice \(D7\.3\)")
        self.assertRegex(text, r"(?i)API emit")
        self.assertIn("hunt:depth_capped", text)

    def test_planes_and_guide_point_at_contract(self) -> None:
        planes = (ROOT / "docs/contracts/graph-planes-v1.md").read_text(encoding="utf-8")
        self.assertIn("hunt-depth-v1.md", planes)
        guide = (ROOT / "docs/docs/guides/graph-analysis.md").read_text(encoding="utf-8")
        self.assertIn("hunt-depth-v1.md", guide)

    def test_claim_lock_additive_honesty(self) -> None:
        lock = (ROOT / "docs/compliance/CLAIM_LOCK.md").read_text(encoding="utf-8")
        self.assertIn("docs/contracts/hunt-depth-v1.md", lock)
        rows = _claim_lock_hunt_rows(lock)
        self.assertIn("hunt-depth-v1", rows)
        self.assertRegex(rows, r"(?i)GRAPH_SERVICE_URL")
        self.assertRegex(rows, r"(?i)\boff\b")

    def test_openapi_subgraph_emits_hunt_depth_fields(self) -> None:
        spec = (ROOT / "contracts/openapi/graph-service.yaml").read_text(encoding="utf-8")
        self.assertIn(SCHEMA_ID, spec)
        for field in SCHEMA_FIELDS:
            self.assertIn(field, spec)
        self.assertIn("hunt:depth_capped", spec)

    def test_path_b_shipped_not_path_a(self) -> None:
        hunt = (ROOT / "docs/contracts/hunt-depth-v1.md").read_text(encoding="utf-8")
        lock_rows = _claim_lock_hunt_rows(
            (ROOT / "docs/compliance/CLAIM_LOCK.md").read_text(encoding="utf-8")
        )
        self.assertRegex(hunt, r"Path B")
        self.assertRegex(hunt, r"D7\.4")
        self.assertRegex(hunt, r"enforced depth-1")
        self.assertIn("age_unnest", hunt)
        self.assertIn("MATCH (root)-[e]-(nb)", hunt)
        self.assertRegex(hunt, r"hunt_depth_max\s*=\s*1")
        self.assertNotRegex(hunt, r"(?i)Path A shipped")
        self.assertRegex(lock_rows, r"Path B")
        self.assertRegex(lock_rows, r"D7\.4")
        self.assertRegex(lock_rows, r"hunt_depth_max=1")
        shipped = hunt.split("## Out of scope")[0]
        for pat in (
            re.compile(r"unlimited", re.I),
            re.compile(r"variable-length", re.I),
            re.compile(r"neo4j[- ]class", re.I),
        ):
            hit = pat.search(shipped)
            self.assertIsNone(hit, f"forbidden {pat.pattern!r} in Path B shipped copy")
        true_cells = []
        for line in lock_rows.splitlines():
            if line.count("|") < 2:
                continue
            cells = [c.strip() for c in line.split("|")]
            if cells and cells[0] == "":
                cells = cells[1:]
            if not cells:
                continue
            true_cells.append(cells[0])
        true_blob = "\n".join(true_cells)
        self.assertRegex(true_blob, r"Path B")
        for pat in (
            re.compile(r"unlimited", re.I),
            re.compile(r"variable-length", re.I),
            re.compile(r"neo4j[- ]class", re.I),
        ):
            hit = pat.search(true_blob)
            self.assertIsNone(hit, f"forbidden {pat.pattern!r} in CLAIM_LOCK true-on-tip Hunt row")

    def test_new_buyer_rows_forbid_incumbent_wording(self) -> None:
        hunt = (ROOT / "docs/contracts/hunt-depth-v1.md").read_text(encoding="utf-8")
        lock = _claim_lock_hunt_rows(
            (ROOT / "docs/compliance/CLAIM_LOCK.md").read_text(encoding="utf-8")
        )
        planes = (ROOT / "docs/contracts/graph-planes-v1.md").read_text(encoding="utf-8")
        plane_add = "\n".join(
            line for line in planes.splitlines() if "hunt-depth" in line or "Hunt depth" in line
        )
        blob = "\n".join((hunt, lock, plane_add))
        for pat in FORBIDDEN:
            hit = pat.search(blob)
            self.assertIsNone(hit, f"forbidden {pat.pattern!r} in new Hunt depth buyer copy")


if __name__ == "__main__":
    raise SystemExit(unittest.main())
