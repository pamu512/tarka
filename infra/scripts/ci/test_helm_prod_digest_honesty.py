#!/usr/bin/env python3
"""G2: prod-on-k8s honesty / publish path fails on empty digest.

Lite/demo are not scanned. Smoke helm template may still use --allow-empty-digest
(limitation / non-grade, not an immutable claim).

Run: python3 infra/scripts/ci/test_helm_prod_digest_honesty.py
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
GEN = ROOT / "infra/scripts/deploy/generate_cloud_values.py"
HONESTY = ROOT / "infra/scripts/ci/helm_prod_digest_honesty.py"
CHART = ROOT / "infra/deploy/helm/fraud-stack"

CORE = "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
SIGNAL = "sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
AGENT = "sha256:cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc"


def _prod_args(out: Path) -> list[str]:
    return [
        "python3",
        str(GEN),
        "--preset",
        "prod-on-k8s",
        "--image-registry",
        "registry.example.com/tarka",
        "--db-url",
        "postgresql+asyncpg://fraud:pw@db.internal:5432/fraud",
        "--redis-url",
        "rediss://elasticache:6379/0",
        "--output",
        str(out),
    ]


class TestHelmProdDigestHonesty(unittest.TestCase):
    def test_empty_digest_values_fail_grade_scan(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "empty.values.yaml"
            gen = subprocess.run(
                [*_prod_args(out), "--allow-empty-digest"],
                cwd=ROOT,
                capture_output=True,
                text=True,
            )
            self.assertEqual(gen.returncode, 0, gen.stderr + gen.stdout)
            scan = subprocess.run(
                ["python3", str(HONESTY), "--values", str(out)],
                cwd=ROOT,
                capture_output=True,
                text=True,
            )
        self.assertNotEqual(scan.returncode, 0, scan.stdout)
        combined = scan.stderr + scan.stdout
        self.assertIn("coreApi", combined)
        self.assertIn("empty digest", combined.lower().replace("_", " "))

    def test_digest_map_values_pass_grade_scan(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "pinned.values.yaml"
            digest_map = Path(td) / "digests.map"
            digest_map.write_text(
                f"coreApi={CORE}\nsignalApi={SIGNAL}\ninvestigationAgent={AGENT}\n",
                encoding="utf-8",
            )
            gen = subprocess.run(
                [*_prod_args(out), "--digest-map", str(digest_map)],
                cwd=ROOT,
                capture_output=True,
                text=True,
            )
            self.assertEqual(gen.returncode, 0, gen.stderr + gen.stdout)
            scan = subprocess.run(
                ["python3", str(HONESTY), "--values", str(out)],
                cwd=ROOT,
                capture_output=True,
                text=True,
            )
            self.assertEqual(scan.returncode, 0, scan.stderr + scan.stdout)
            helm = shutil.which("helm")
            if helm is None:
                return
            rendered = subprocess.run(
                [helm, "template", "tarka", str(CHART), "-f", str(out)],
                cwd=ROOT,
                check=True,
                capture_output=True,
                text=True,
            ).stdout
        self.assertIn(f"tarka-core-api@{CORE}", rendered)
        self.assertIn(f"tarka-signal-api@{SIGNAL}", rendered)

    def test_lite_values_are_not_a_grade_fail(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "lite.values.yaml"
            gen = subprocess.run(
                [
                    "python3",
                    str(GEN),
                    "--preset",
                    "lite-on-k8s",
                    "--image-registry",
                    "registry.example.com/tarka",
                    "--output",
                    str(out),
                ],
                cwd=ROOT,
                capture_output=True,
                text=True,
            )
            self.assertEqual(gen.returncode, 0, gen.stderr + gen.stdout)
            scan = subprocess.run(
                ["python3", str(HONESTY), "--values", str(out)],
                cwd=ROOT,
                capture_output=True,
                text=True,
            )
        # lite is not the prod-on-k8s publish path — skip / OK, never a grade fail
        self.assertEqual(scan.returncode, 0, scan.stderr + scan.stdout)

    def test_self_check_passes(self) -> None:
        r = subprocess.run(
            ["python3", str(HONESTY), "--self-check"],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)


if __name__ == "__main__":
    raise SystemExit(unittest.main())
