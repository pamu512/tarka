#!/usr/bin/env python3
"""Helm template upgrade dry-run between two beta digests.

No cluster. Renders prod-on-k8s at digest A then digest B and asserts the
workload inventory is stable (image pin is the only intended change).
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

_REPO = Path(__file__).resolve().parents[3]
_CHART = _REPO / "infra" / "deploy" / "helm" / "fraud-stack"
_GEN = _REPO / "infra" / "scripts" / "deploy" / "generate_cloud_values.py"
_DIGEST_A = "sha256:" + "a" * 64
_DIGEST_B = "sha256:" + "b" * 64


def _helm(*extra: str) -> str:
    helm = shutil.which("helm")
    if not helm:
        raise unittest.SkipTest("helm is not installed")
    cmd = [helm, "template", "tarka", str(_CHART), *extra]
    r = subprocess.run(cmd, cwd=str(_REPO), capture_output=True, text=True)
    if r.returncode != 0:
        raise AssertionError(f"helm template failed ({r.returncode}):\n{r.stderr}\n{r.stdout}")
    return r.stdout


def _resource_keys(rendered: str) -> list[tuple[str, str]]:
    keys: list[tuple[str, str]] = []
    kind = ""
    for raw in rendered.splitlines():
        line = raw.rstrip()
        if line.startswith("kind:"):
            kind = line.split(":", 1)[1].strip()
        elif kind and line.startswith("  name:"):
            keys.append((kind, line.split(":", 1)[1].strip()))
            kind = ""
    return keys


def _prod_values(tmp: Path) -> Path:
    out = tmp / "prod-on-k8s.values.yaml"
    gen = subprocess.run(
        [
            sys.executable,
            str(_GEN),
            "--preset",
            "prod-on-k8s",
            "--image-registry",
            "registry.example.com/tarka",
            "--db-url",
            "postgresql+asyncpg://fraud:pw@db.internal:5432/fraud",
            "--redis-url",
            "rediss://redis.internal:6379/0",
            "--output",
            str(out),
            # ponytail: G2 requires --digest-map for a grade pin; this dry-run
            # overlays digest A/B via helm --set. Upgrade to --digest-map files
            # if generate stops emitting overlay-able empty digest values.
            "--allow-empty-digest",
        ],
        cwd=str(_REPO),
        capture_output=True,
        text=True,
    )
    if gen.returncode != 0:
        raise AssertionError(gen.stderr + gen.stdout)
    return out


def _digest_sets(digest: str) -> list[str]:
    return [
        "--set",
        f"coreApi.digest={digest}",
        "--set",
        f"signalApi.digest={digest}",
        "--set",
        f"investigationAgent.digest={digest}",
    ]


class TestHelmUpgradeDryRun(unittest.TestCase):
    def test_digest_a_to_digest_b_keeps_inventory(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            values = _prod_values(Path(td))
            before = _helm("-f", str(values), *_digest_sets(_DIGEST_A))
            after = _helm("-f", str(values), *_digest_sets(_DIGEST_B))

        self.assertIn(f"@{_DIGEST_A}", before)
        self.assertNotIn(f"@{_DIGEST_B}", before)
        self.assertIn(f"@{_DIGEST_B}", after)
        self.assertNotIn(f"@{_DIGEST_A}", after)
        self.assertNotIn("tarka-core-api:1.3.0-beta", before)
        self.assertNotIn("tarka-core-api:1.3.0-beta", after)

        self.assertEqual(_resource_keys(before), _resource_keys(after))
        kinds = {k for k, _ in _resource_keys(before)}
        self.assertIn("Deployment", kinds)
        self.assertIn("Service", kinds)
        self.assertNotIn("PersistentVolumeClaim", kinds)
        self.assertNotIn("kind: StatefulSet", before)
        names = {n for _, n in _resource_keys(before)}
        self.assertTrue(any("core-api" in n for n in names))
        self.assertFalse(any(n.endswith("-postgres") and "age" not in n for n in names))

    def test_beta_tag_to_digest_is_image_only(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            values = _prod_values(Path(td))
            tagged = _helm("-f", str(values))
            pinned = _helm("-f", str(values), *_digest_sets(_DIGEST_A))
        self.assertIn("tarka-core-api:1.3.0-beta", tagged)
        self.assertIn(f"@{_DIGEST_A}", pinned)
        self.assertEqual(_resource_keys(tagged), _resource_keys(pinned))


if __name__ == "__main__":
    raise SystemExit(unittest.main())
