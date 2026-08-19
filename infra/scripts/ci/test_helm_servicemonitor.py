#!/usr/bin/env python3
"""Helm ServiceMonitor gate: default chart emits none; environment=prod emits enabled APIs."""

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


def _helm(*extra: str) -> str:
    helm = shutil.which("helm")
    if not helm:
        raise unittest.SkipTest("helm is not installed")
    cmd = [helm, "template", "tarka", str(_CHART), *extra]
    r = subprocess.run(cmd, cwd=str(_REPO), capture_output=True, text=True)
    if r.returncode != 0:
        raise AssertionError(f"helm template failed ({r.returncode}):\n{r.stderr}\n{r.stdout}")
    return r.stdout


def _documents(rendered: str) -> list[str]:
    return [part.strip() for part in rendered.split("\n---\n") if part.strip()]


def _kind_docs(rendered: str, kind: str) -> list[str]:
    return [doc for doc in _documents(rendered) if f"\nkind: {kind}\n" in f"\n{doc}\n"]


def _doc_name(doc: str) -> str:
    for line in doc.splitlines():
        if line.startswith("  name:"):
            return line.split(":", 1)[1].strip()
    return ""


def _kind_names(rendered: str, kind: str) -> list[str]:
    return [_doc_name(doc) for doc in _kind_docs(rendered, kind)]


class TestHelmServiceMonitor(unittest.TestCase):
    def test_default_values_emit_no_servicemonitor(self) -> None:
        rendered = _helm("-f", str(_CHART / "values.yaml"))
        self.assertNotIn("kind: ServiceMonitor", rendered)
        self.assertEqual(_kind_names(rendered, "ServiceMonitor"), [])

    def test_environment_prod_emits_monitors_for_enabled_apis(self) -> None:
        rendered = _helm(
            "--set",
            "global.environment=prod",
            "--set",
            "coreApi.extraEnv.TARKA_EVALUATE_REQUIRE_IDEMPOTENCY_KEY=true",
            "--set",
            "dataPlane.extraEnv.INGEST_REQUIRE_IDEMPOTENCY_KEY=true",
            "--set",
            "signalApi.enabled=true",
            "--set",
            "investigationAgent.enabled=true",
            "--set",
            "investigationAgent.extraEnv.COPILOT_PRODUCTION_MODE=true",
        )
        names = _kind_names(rendered, "ServiceMonitor")
        self.assertEqual(
            names,
            [
                "tarka-tarka-core-api",
                "tarka-tarka-signal-api",
                "tarka-tarka-investigation-agent",
            ],
        )
        for doc in _kind_docs(rendered, "ServiceMonitor"):
            self.assertIn("apiVersion: monitoring.coreos.com/v1", doc)
            self.assertIn("path: /metrics", doc)
            self.assertIn("interval: 30s", doc)
            self.assertIn("port: http", doc)
            name = _doc_name(doc)
            self.assertIn(f"app: {name}", doc)

    def test_disabled_workload_emits_no_monitor(self) -> None:
        rendered = _helm(
            "--set",
            "global.environment=prod",
            "--set",
            "coreApi.extraEnv.TARKA_EVALUATE_REQUIRE_IDEMPOTENCY_KEY=true",
            "--set",
            "dataPlane.extraEnv.INGEST_REQUIRE_IDEMPOTENCY_KEY=true",
            "--set",
            "coreApi.enabled=false",
            "--set",
            "signalApi.enabled=true",
        )
        names = _kind_names(rendered, "ServiceMonitor")
        self.assertEqual(names, ["tarka-tarka-signal-api"])
        self.assertNotIn("tarka-tarka-core-api", names)
        self.assertNotIn("tarka-tarka-investigation-agent", names)

    def test_prod_on_k8s_preset_emits_core_and_signal(self) -> None:
        if not _GEN.exists():
            raise unittest.SkipTest("generate_cloud_values.py missing")
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "prod-on-k8s.values.yaml"
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
                ],
                cwd=str(_REPO),
                capture_output=True,
                text=True,
            )
            self.assertEqual(gen.returncode, 0, msg=gen.stderr + gen.stdout)
            rendered = _helm("-f", str(out))
        names = _kind_names(rendered, "ServiceMonitor")
        self.assertIn("tarka-tarka-core-api", names)
        self.assertIn("tarka-tarka-signal-api", names)
        self.assertIn("tarka-tarka-investigation-agent", names)


if __name__ == "__main__":
    raise SystemExit(unittest.main())
