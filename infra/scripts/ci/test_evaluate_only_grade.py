#!/usr/bin/env python3
"""R7: evaluate-only preset graduates to the production-install grade path.

CE-shaped buyers get a thin HA install: external Postgres/Redis (in-cluster off),
sha256 digest discipline (same GRADE_PRESETS gate as prod-on-k8s), production
fail-closed env (profile, idempotency, case production mode), frontend OFF per
grade policy (desk is make product / enterprise-desk, not this chart).
In-cluster day-1 shape remains plain values.yaml defaults.
"""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PRESET = ROOT / "infra/deploy/helm/fraud-stack/presets/evaluate-only.yaml"
GEN = ROOT / "infra/scripts/deploy/generate_cloud_values.py"


def _load_gen():
    spec = importlib.util.spec_from_file_location("generate_cloud_values", GEN)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestEvaluateOnlyGradePath(unittest.TestCase):
    def setUp(self):
        self.text = PRESET.read_text()

    def test_external_stores_required_placeholders(self):
        self.assertIn("__DB_URL__", self.text)
        self.assertIn("__REDIS_URL__", self.text)
        self.assertRegex(self.text, r"postgres:\s*\n\s*enabled:\s*false")
        self.assertRegex(self.text, r"redis:\s*\n\s*enabled:\s*false")

    def test_core_api_only_with_prod_fail_closes(self):
        self.assertIn("TARKA_DEPLOYMENT_PROFILE: production", self.text)
        self.assertIn('TARKA_EVALUATE_REQUIRE_IDEMPOTENCY_KEY: "true"', self.text)
        self.assertIn('CASE_API_PRODUCTION_MODE: "true"', self.text)
        self.assertIn("allowInsecureNoAuth: false", self.text)
        self.assertIn('digest: ""', self.text)  # empty = limitation; --digest-map fills

    def test_frontend_off_grade_policy(self):
        self.assertRegex(self.text, r"frontend:\s*\n\s*enabled:\s*false")

    def test_no_optional_planes_enabled(self):
        for plane in (
            "signalApi",
            "investigationAgent",
            "integrationIngress",
            "dataPlane",
            "graphService",
            "nats",
            "clickhouse",
            "orchestrator",
        ):
            self.assertRegex(self.text, rf"{plane}:\s*\n\s*enabled:\s*false", plane)

    def test_generator_treats_evaluate_only_as_grade_preset(self):
        mod = _load_gen()
        self.assertIn("evaluate-only", mod.GRADE_PRESETS)

    def test_generator_requires_digest_map_for_evaluate_only(self):
        mod = _load_gen()
        argv = [
            sys.argv[0],
            "--preset",
            "evaluate-only",
            "--db-url",
            "postgresql+asyncpg://u:p@db:5432/fraud",
            "--redis-url",
            "rediss://cache:6379/0",
            "--image-registry",
            "reg.example/tarka",
            "--output",
            "/tmp/_eo_should_not_exist.yaml",
        ]
        old = sys.argv
        sys.argv = argv
        try:
            with self.assertRaises(SystemExit) as cm:
                mod.main()
            self.assertIn("digest-map", str(cm.exception))
        finally:
            sys.argv = old


if __name__ == "__main__":
    unittest.main()
