#!/usr/bin/env python3
"""Helm guard (B3): data-plane exposes first-class ORCHESTRATOR_URL wiring.

docker-compose.yml wires ORCHESTRATOR_URL + ORCHESTRATOR_INTERNAL_SECRET into the
data-plane facade; the chart never did, so the ingest consumer silently skipped
orchestrator side-effect commits on Helm deploys. Default (orchestrator
disabled) must NOT emit the env (unset URL = skip; pointing the consumer at a
dead host would wedge side-effects). Setting dataPlane.orchestratorUrl renders
both envs — secret via secretKeyRef when global.appSecretsName is set,
plaintext value otherwise. URL-without-secret renders too: event-ingest logs
that misconfiguration loudly at startup (D1). Auto-wiring from
orchestrator.enabled is covered in test_helm_orchestrator_workers.py.
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


def _data_plane_deployment(rendered: str) -> str:
    for doc in rendered.split("\n---\n"):
        if "kind: Deployment" in doc and "tarka-tarka-data-plane" in doc:
            return doc
    raise AssertionError("data-plane Deployment missing from render")


def _env_entry(doc: str, name: str) -> str:
    lines = doc.splitlines()
    for i, line in enumerate(lines):
        if line.strip() == f"- name: {name}":
            chunk = [line]
            for follow in lines[i + 1 :]:
                if follow.strip().startswith("- name:"):
                    break
                chunk.append(follow)
            return "\n".join(chunk)
    raise AssertionError(f"env {name!r} not found in data-plane render")


class TestDataPlaneOrchestratorWiring(unittest.TestCase):
    def test_default_render_omits_orchestrator_env(self) -> None:
        """Chart deploys no orchestrator: default must not point the consumer anywhere."""
        doc = _data_plane_deployment(_helm("-f", str(_CHART / "values.yaml")))
        self.assertNotIn("ORCHESTRATOR_URL", doc)
        self.assertNotIn("ORCHESTRATOR_INTERNAL_SECRET", doc)

    def test_orchestrator_url_renders_url_and_secret(self) -> None:
        doc = _data_plane_deployment(
            _helm(
                "-f",
                str(_CHART / "values.yaml"),
                "--set",
                "dataPlane.orchestratorUrl=http://orchestrator:8790",
                "--set",
                "dataPlane.orchestratorInternalSecret=dev-secret",
            )
        )
        self.assertIn('value: "http://orchestrator:8790"', _env_entry(doc, "ORCHESTRATOR_URL"))
        self.assertIn('value: "dev-secret"', _env_entry(doc, "ORCHESTRATOR_INTERNAL_SECRET"))

    def test_orchestrator_secret_uses_secret_ref_when_app_secrets_set(self) -> None:
        doc = _data_plane_deployment(
            _helm(
                "-f",
                str(_CHART / "values.yaml"),
                "--set",
                "dataPlane.orchestratorUrl=http://orchestrator:8790",
                "--set",
                "global.appSecretsName=tarka-app-secrets",
            )
        )
        entry = _env_entry(doc, "ORCHESTRATOR_INTERNAL_SECRET")
        self.assertIn("secretKeyRef", entry)
        self.assertIn('name: "tarka-app-secrets"', entry)
        self.assertIn("key: ORCHESTRATOR_INTERNAL_SECRET", entry)
        self.assertIn("optional: true", entry)
        self.assertNotIn("value:", entry)  # no plaintext slot when the secret ref is active

    def test_url_without_secret_renders_for_dev_posture(self) -> None:
        """URL set + empty secret renders; event-ingest fails loudly at startup (D1)."""
        doc = _data_plane_deployment(
            _helm(
                "-f",
                str(_CHART / "values.yaml"),
                "--set",
                "dataPlane.orchestratorUrl=http://orchestrator:8790",
            )
        )
        self.assertIn('value: ""', _env_entry(doc, "ORCHESTRATOR_INTERNAL_SECRET"))


if __name__ == "__main__":
    unittest.main()
