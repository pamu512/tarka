#!/usr/bin/env python3
"""Helm honesty: Jev Advise gate env is investigation-agent only.

Empty JEV_SYSTEM_ONE_URL and JEV_MODE=shadow are the chart defaults.
core-api (evaluate) must not receive these keys.
"""

from __future__ import annotations

import shutil
import subprocess
import unittest
from pathlib import Path

_REPO = Path(__file__).resolve().parents[3]
_CHART = _REPO / "infra" / "deploy" / "helm" / "fraud-stack"

_KEYS = {
    "JEV_SYSTEM_ONE_URL": "",
    "JEV_TIMEOUT_MS": "400",
    "JEV_MIN_CONFIDENCE": "0.55",
    "JEV_MODE": "shadow",
    "JEV_QUESTION_PACK": "advise_sufficiency_v1",
}


def _helm(*extra: str) -> str:
    helm = shutil.which("helm")
    if not helm:
        raise unittest.SkipTest("helm is not installed")
    cmd = [helm, "template", "tarka", str(_CHART), *extra]
    result = subprocess.run(cmd, cwd=str(_REPO), capture_output=True, text=True)
    if result.returncode != 0:
        raise AssertionError(
            f"helm template failed ({result.returncode}):\n{result.stderr}\n{result.stdout}"
        )
    return result.stdout


def _docs(rendered: str) -> list[str]:
    return [doc for doc in rendered.split("\n---\n") if doc.strip()]


def _deployment(rendered: str, name_suffix: str) -> str:
    for doc in _docs(rendered):
        if "kind: Deployment" in doc and f"name: tarka-tarka-{name_suffix}" in doc:
            return doc
    raise AssertionError(f"{name_suffix} Deployment missing from render")


def _env_value(doc: str, name: str) -> str:
    lines = doc.splitlines()
    for i, line in enumerate(lines):
        if line.strip() == f"- name: {name}":
            for follow in lines[i + 1 :]:
                stripped = follow.strip()
                if stripped.startswith("- name:"):
                    break
                if stripped.startswith("value:"):
                    raw = stripped.split(":", 1)[1].strip()
                    if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in "\"'":
                        return raw[1:-1]
                    return raw
            raise AssertionError(f"env {name!r} has no value:")
    raise AssertionError(f"env {name!r} not found")


class TestHelmJevAdviseHonesty(unittest.TestCase):
    def test_default_render_does_not_put_jev_on_evaluate(self) -> None:
        rendered = _helm("-f", str(_CHART / "values.yaml"))
        self.assertNotIn("JEV_SYSTEM_ONE_URL", rendered)
        self.assertNotIn("JEV_MODE", rendered)
        self.assertNotIn("JEV_API_KEY", rendered)

    def test_enabled_agent_emits_defaults_and_evaluate_stays_clean(self) -> None:
        rendered = _helm(
            "-f",
            str(_CHART / "values.yaml"),
            "--set",
            "investigationAgent.enabled=true",
        )
        agent = _deployment(rendered, "investigation-agent")
        for key, expected in _KEYS.items():
            self.assertEqual(_env_value(agent, key), expected)
        core = _deployment(rendered, "core-api")
        self.assertNotIn("JEV_", core)
        self.assertEqual(rendered.count("name: JEV_SYSTEM_ONE_URL"), 1)
        self.assertNotIn("name: JEV_API_KEY", rendered)

    def test_first_class_wins_over_extra_env(self) -> None:
        rendered = _helm(
            "-f",
            str(_CHART / "values.yaml"),
            "--set",
            "investigationAgent.enabled=true",
            "--set-string",
            "investigationAgent.extraEnv.JEV_MODE=gate",
            "--set-string",
            "investigationAgent.extraEnv.JEV_SYSTEM_ONE_URL=http://jev.invalid",
            "--set-string",
            "investigationAgent.extraEnv.JEV_API_KEY=super-secret",
            "--set-string",
            "global.appSecretsName=tarka-app-secrets",
        )
        agent = _deployment(rendered, "investigation-agent")
        self.assertEqual(_env_value(agent, "JEV_MODE"), "shadow")
        self.assertEqual(_env_value(agent, "JEV_SYSTEM_ONE_URL"), "")
        self.assertEqual(agent.count("name: JEV_MODE"), 1)
        self.assertEqual(agent.count("name: JEV_SYSTEM_ONE_URL"), 1)
        self.assertNotIn("super-secret", rendered)
        self.assertIn("key: JEV_API_KEY", agent)
        self.assertEqual(agent.count("name: JEV_API_KEY"), 1)

    def test_bad_mode_fails_render(self) -> None:
        helm = shutil.which("helm")
        if not helm:
            self.skipTest("helm is not installed")
        cmd = [
            helm,
            "template",
            "tarka",
            str(_CHART),
            "-f",
            str(_CHART / "values.yaml"),
            "--set",
            "investigationAgent.enabled=true",
            "--set-string",
            "investigationAgent.jev.mode=promote",
        ]
        result = subprocess.run(cmd, cwd=str(_REPO), capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("investigationAgent.jev.mode", result.stderr + result.stdout)


if __name__ == "__main__":
    raise SystemExit(unittest.main())
