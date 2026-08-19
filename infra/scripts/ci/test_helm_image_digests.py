#!/usr/bin/env python3
"""Helm image digest render tests (stdlib). Requires helm on PATH.

Run: python3 infra/scripts/ci/test_helm_image_digests.py
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
CHART = ROOT / "infra/deploy/helm/fraud-stack"
DUMMY_DIGEST = (
    "sha256:deadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeef"
)
GEN = ROOT / "infra/scripts/deploy/generate_cloud_values.py"


def _helm(*args: str) -> str:
    helm = shutil.which("helm")
    if not helm:
        raise unittest.SkipTest("helm is not installed")
    proc = subprocess.run(
        [helm, *args],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return proc.stdout


class TestHelmImageDigests(unittest.TestCase):
    def test_default_template_uses_tags(self) -> None:
        rendered = _helm(
            "template",
            "tarka",
            str(CHART),
            "-f",
            str(CHART / "values.yaml"),
        )
        self.assertIn("tarka-core-api:latest", rendered)
        self.assertNotIn("@sha256:", rendered)

    def test_core_api_digest_renders_at_sha256(self) -> None:
        rendered = _helm(
            "template",
            "tarka",
            str(CHART),
            "-f",
            str(CHART / "values.yaml"),
            "--set",
            f"coreApi.digest={DUMMY_DIGEST}",
        )
        self.assertIn(f"tarka-core-api@{DUMMY_DIGEST}", rendered)
        self.assertNotIn("tarka-core-api:latest", rendered)

    def test_empty_digest_prod_on_k8s_still_templates(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "prod-on-k8s.values.yaml"
            subprocess.run(
                [
                    "python3",
                    str(GEN),
                    "--preset",
                    "prod-on-k8s",
                    "--image-registry",
                    "registry.example.com/tarka",
                    "--db-url",
                    "postgresql+asyncpg://fraud:pw@db.internal:5432/fraud",
                    "--redis-url",
                    "redis://redis.internal:6379/0",
                    "--output",
                    str(out),
                ],
                cwd=ROOT,
                check=True,
                capture_output=True,
                text=True,
            )
            rendered = _helm("template", "tarka", str(CHART), "-f", str(out))
        self.assertIn("tarka-core-api:1.3.0-beta", rendered)
        self.assertIn("tarka-signal-api:1.3.0-beta", rendered)
        self.assertNotIn("@sha256:", rendered)


if __name__ == "__main__":
    raise SystemExit(unittest.main())
