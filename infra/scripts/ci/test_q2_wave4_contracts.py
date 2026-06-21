#!/usr/bin/env python3
"""Q2 Wave 4 contract tests (stdlib); run: python3 infra/scripts/ci/test_q2_wave4_contracts.py"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
GRAPH_SRC = ROOT / "services/graph-service/src"
if str(GRAPH_SRC) not in sys.path:
    sys.path.insert(0, str(GRAPH_SRC))


class TestGraphPathExplanationSchema(unittest.TestCase):
    def test_schema_file_valid(self) -> None:
        path = ROOT / "contracts/schemas/tarka-graph-path-explanation-v1.schema.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(data["properties"]["schema_id"]["const"], "tarka.graph_path_explanation/v1")


class TestPathExplainAssembly(unittest.TestCase):
    def test_assemble_minimal(self) -> None:
        from graph_service.path_explain import assemble_path_explanation

        out = assemble_path_explanation(
            "tenant-1",
            "entity-a",
            [
                {
                    "entity_id": "entity-b",
                    "entity_labels": [],
                    "propagated_risk_score": 40.0,
                    "distance": 1,
                    "node_chain": ["entity-a", "entity-b"],
                    "rel_types": ["USED"],
                }
            ],
        )
        self.assertEqual(out["schema_id"], "tarka.graph_path_explanation/v1")
        self.assertIn("risk_narrative", out)
        self.assertEqual(len(out["paths"]), 1)
        self.assertTrue(out["paths"][0]["path_description"])


class TestOpenApiPaths(unittest.TestCase):
    def test_graph_service_path_explain_in_openapi(self) -> None:
        import yaml

        spec = yaml.safe_load(
            (ROOT / "contracts/openapi/graph-service.yaml").read_text(encoding="utf-8")
        )
        self.assertIn("/v1/analytics/path-explain", spec.get("paths", {}))

    def test_decision_api_benchmark_export_in_openapi(self) -> None:
        import yaml

        spec = yaml.safe_load(
            (ROOT / "contracts/openapi/decision-api.yaml").read_text(encoding="utf-8")
        )
        self.assertIn("/v1/simulation/benchmark/export", spec.get("paths", {}))
        self.assertIn("/v1/drift/query", spec.get("paths", {}))


if __name__ == "__main__":
    raise SystemExit(unittest.main())
