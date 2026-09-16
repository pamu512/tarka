#!/usr/bin/env python3
"""Helm guard: orchestrator + worker family parity with docker-compose.

docker-compose's streaming/analytics/full profiles run five workloads from one
image (services/orchestrator/Dockerfile): the orchestrator API itself plus four
`python -m workers.*` sidecars (outbox-processor, shadow-investigate-worker,
anumana-duck-sink, anumana-heartbeat-monitor). The chart deployed none of them,
so a Helm deployment accumulated outbox rows with nothing draining them (E3
made the outbox load-bearing with stale-claim reclaim). These tests pin the
parity contract: enabled flags gate each Deployment, workers override the
uvicorn ENTRYPOINT, and the duck-sink gets its persisted volume.
"""

from __future__ import annotations

import shutil
import subprocess
import unittest
from pathlib import Path

_REPO = Path(__file__).resolve().parents[3]
_CHART = _REPO / "infra" / "deploy" / "helm" / "fraud-stack"


def _helm(*extra: str) -> str:
    helm = shutil.which("helm")
    if not helm:
        raise unittest.SkipTest("helm is not installed")
    cmd = [helm, "template", "tarka", str(_CHART), *extra]
    r = subprocess.run(cmd, cwd=str(_REPO), capture_output=True, text=True)
    if r.returncode != 0:
        raise AssertionError(f"helm template failed ({r.returncode}):\n{r.stderr}\n{r.stdout}")
    return r.stdout


def _deployment(rendered: str, name: str) -> str:
    for doc in rendered.split("\n---\n"):
        if "kind: Deployment" in doc and f"name: tarka-tarka-{name}" in doc:
            return doc
    raise AssertionError(f"Deployment {name!r} missing from render")


class TestOrchestratorDeployment(unittest.TestCase):
    def test_disabled_by_default(self) -> None:
        """Default chart keeps today's posture: no orchestrator workloads."""
        rendered = _helm("-f", str(_CHART / "values.yaml"))
        self.assertNotIn("tarka-tarka-orchestrator", rendered)

    def test_enabled_renders_api_deployment_and_service(self) -> None:
        rendered = _helm(
            "-f", str(_CHART / "values.yaml"),
            "--set", "orchestrator.enabled=true",
        )
        doc = _deployment(rendered, "orchestrator")
        self.assertIn("image:", doc)
        self.assertIn("containerPort: 8790", doc)
        # Service must exist so data-plane can point ORCHESTRATOR_URL at it
        self.assertIn("kind: Service", rendered.split("kind: Deployment")[0] or rendered)
        self.assertIn(f"-orchestrator", rendered)


class TestWorkerFamily(unittest.TestCase):
    def test_outbox_processor_enabled_by_default_with_orchestrator(self) -> None:
        rendered = _helm(
            "-f", str(_CHART / "values.yaml"),
            "--set", "orchestrator.enabled=true",
        )
        doc = _deployment(rendered, "outbox-processor")
        # workers override the image ENTRYPOINT (python -m uvicorn)
        self.assertIn("command:", doc)
        self.assertIn("-m", doc)
        self.assertIn("workers.outbox_processor", doc)

    def test_shadow_worker_toggles_independently(self) -> None:
        rendered = _helm(
            "-f", str(_CHART / "values.yaml"),
            "--set", "orchestrator.enabled=true",
            "--set", "orchestrator.workers.shadowInvestigate.enabled=false",
        )
        self.assertNotIn("tarka-tarka-shadow-investigate-worker", rendered)
        # and enabled by default when orchestrator is on
        rendered2 = _helm(
            "-f", str(_CHART / "values.yaml"),
            "--set", "orchestrator.enabled=true",
        )
        self.assertIn("tarka-tarka-shadow-investigate-worker", rendered2)

    def test_duck_sink_has_persistent_volume(self) -> None:
        rendered = _helm(
            "-f", str(_CHART / "values.yaml"),
            "--set", "orchestrator.enabled=true",
        )
        doc = _deployment(rendered, "anumana-duck-sink")
        self.assertIn("persistentVolumeClaim", doc)
        self.assertIn("/data", doc)
        lines = doc.splitlines()
        idx = [i for i, ln in enumerate(lines) if "name: ORCHESTRATOR_LOCAL_ANALYTICS_DUCKDB" in ln]
        self.assertTrue(idx, "duckdb path env missing")
        self.assertIn("/data/", "".join(lines[idx[0] : idx[0] + 3]))

    def test_heartbeat_monitor_rendered(self) -> None:
        rendered = _helm(
            "-f", str(_CHART / "values.yaml"),
            "--set", "orchestrator.enabled=true",
        )
        doc = _deployment(rendered, "anumana-heartbeat-monitor")
        self.assertIn("workers.sdk_heartbeat_monitor", doc)

    def test_no_worker_renders_when_orchestrator_disabled(self) -> None:
        rendered = _helm("-f", str(_CHART / "values.yaml"))
        for name in (
            "outbox-processor",
            "shadow-investigate-worker",
            "anumana-duck-sink",
            "anumana-heartbeat-monitor",
        ):
            self.assertNotIn(f"tarka-tarka-{name}", rendered)


def _data_plane(rendered: str) -> str:
    for doc in rendered.split("\n---\n"):
        if "kind: Deployment" in doc and "name: tarka-tarka-data-plane" in doc:
            return doc
    raise AssertionError("data-plane Deployment missing from render")


def _env_entry(doc: str, name: str) -> str:
    lines = doc.splitlines()
    for i, line in enumerate(lines):
        if line.strip() == f"- name: {name}":
            chunk = [line]
            for follow in lines[i + 1:]:
                if follow.strip().startswith("- name:"):
                    break
                chunk.append(follow)
            return "\n".join(chunk)
    raise AssertionError(f"env {name!r} not found")


class TestDataPlaneAutoWiring(unittest.TestCase):
    def test_enabling_orchestrator_points_data_plane_at_it(self) -> None:
        """orchestrator.enabled must auto-wire ORCHESTRATOR_URL unless overridden."""
        doc = _data_plane(_helm(
            "-f", str(_CHART / "values.yaml"),
            "--set", "orchestrator.enabled=true",
        ))
        entry = _env_entry(doc, "ORCHESTRATOR_URL")
        self.assertIn("tarka-tarka-orchestrator:8790", entry)

    def test_explicit_url_still_wins(self) -> None:
        doc = _data_plane(_helm(
            "-f", str(_CHART / "values.yaml"),
            "--set", "orchestrator.enabled=true",
            "--set", "dataPlane.orchestratorUrl=http://elsewhere:8790",
        ))
        entry = _env_entry(doc, "ORCHESTRATOR_URL")
        self.assertIn("http://elsewhere:8790", entry)


if __name__ == "__main__":
    unittest.main()
