#!/usr/bin/env python3
"""Helm honesty: Settings-owned circuit knobs render into core-api env.

decision-api Settings owns ANUMANA_SIGNALS_* / ASYNC_OSINT_REDIS_* (defaults
unchanged). This chart must emit those eight keys on the core-api Deployment
env — values-only prose without template wiring is a prod Helm lie.
Planes are SKIP/soft-fail optional; not required HA.
"""

from __future__ import annotations

import shutil
import subprocess
import unittest
from pathlib import Path

_REPO = Path(__file__).resolve().parents[3]
_CHART = _REPO / "infra" / "deploy" / "helm" / "fraud-stack"

# Must match services/decision-api/tests/test_circuit_settings.py defaults.
_DEFAULTS: dict[str, str] = {
    "ANUMANA_SIGNALS_TIMEOUT_SECONDS": "0.08",
    "ANUMANA_SIGNALS_MAX_ATTEMPTS": "1",
    "ANUMANA_SIGNALS_CIRCUIT_FAILURE_THRESHOLD": "5",
    "ANUMANA_SIGNALS_CIRCUIT_RECOVERY_SECONDS": "2.0",
    "ASYNC_OSINT_REDIS_TIMEOUT_SECONDS": "0.08",
    "ASYNC_OSINT_REDIS_MAX_ATTEMPTS": "1",
    "ASYNC_OSINT_REDIS_CIRCUIT_FAILURE_THRESHOLD": "5",
    "ASYNC_OSINT_REDIS_CIRCUIT_RECOVERY_SECONDS": "2.0",
}


def _helm(*extra: str) -> str:
    helm = shutil.which("helm")
    if not helm:
        raise unittest.SkipTest("helm is not installed")
    cmd = [helm, "template", "tarka", str(_CHART), *extra]
    r = subprocess.run(cmd, cwd=str(_REPO), capture_output=True, text=True)
    if r.returncode != 0:
        raise AssertionError(
            f"helm template failed ({r.returncode}):\n{r.stderr}\n{r.stdout}"
        )
    return r.stdout


def _core_api_deployment(rendered: str) -> str:
    for doc in rendered.split("\n---\n"):
        if "kind: Deployment" in doc and "name: tarka-tarka-core-api" in doc:
            return doc
    raise AssertionError("core-api Deployment missing from render")


def _env_value(doc: str, name: str) -> str:
    lines = doc.splitlines()
    for i, line in enumerate(lines):
        if line.strip() == f"- name: {name}":
            for follow in lines[i + 1 :]:
                stripped = follow.strip()
                if stripped.startswith("- name:"):
                    break
                if stripped.startswith("value:"):
                    # helm | quote → value: "…"
                    raw = stripped.split(":", 1)[1].strip()
                    if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in "\"'":
                        return raw[1:-1]
                    return raw
            raise AssertionError(f"env {name!r} has no value:")
    raise AssertionError(f"env {name!r} not found in core-api Deployment")


class TestHelmCircuitSettingsHonesty(unittest.TestCase):
    def test_default_render_emits_eight_keys_on_core_api(self) -> None:
        doc = _core_api_deployment(_helm("-f", str(_CHART / "values.yaml")))
        for key, expected in _DEFAULTS.items():
            self.assertEqual(
                _env_value(doc, key),
                expected,
                f"{key} must appear on core-api env with Settings default",
            )

    def test_values_path_override_changes_rendered_env(self) -> None:
        """Proves wiring: --set on circuitSettings reaches Deployment env."""
        doc = _core_api_deployment(
            _helm(
                "-f",
                str(_CHART / "values.yaml"),
                "--set-string",
                "coreApi.circuitSettings.anumanaSignals.timeoutSeconds=0.25",
                "--set-string",
                "coreApi.circuitSettings.asyncOsintRedis.circuitRecoverySeconds=9.5",
            )
        )
        self.assertEqual(_env_value(doc, "ANUMANA_SIGNALS_TIMEOUT_SECONDS"), "0.25")
        self.assertEqual(
            _env_value(doc, "ASYNC_OSINT_REDIS_CIRCUIT_RECOVERY_SECONDS"), "9.5"
        )
        # Untouched keys keep chart defaults.
        self.assertEqual(_env_value(doc, "ANUMANA_SIGNALS_MAX_ATTEMPTS"), "1")
        self.assertEqual(_env_value(doc, "ASYNC_OSINT_REDIS_MAX_ATTEMPTS"), "1")

    def test_first_class_wins_over_extra_env(self) -> None:
        doc = _core_api_deployment(
            _helm(
                "-f",
                str(_CHART / "values.yaml"),
                "--set-string",
                "coreApi.extraEnv.ANUMANA_SIGNALS_TIMEOUT_SECONDS=9.99",
                "--set-string",
                "coreApi.extraEnv.ASYNC_OSINT_REDIS_MAX_ATTEMPTS=99",
            )
        )
        self.assertEqual(_env_value(doc, "ANUMANA_SIGNALS_TIMEOUT_SECONDS"), "0.08")
        self.assertEqual(_env_value(doc, "ASYNC_OSINT_REDIS_MAX_ATTEMPTS"), "1")
        # Duplicate names must not appear (extraEnv filtered).
        self.assertEqual(doc.count("name: ANUMANA_SIGNALS_TIMEOUT_SECONDS"), 1)
        self.assertEqual(doc.count("name: ASYNC_OSINT_REDIS_MAX_ATTEMPTS"), 1)


if __name__ == "__main__":
    raise SystemExit(unittest.main())
