#!/usr/bin/env python3
"""Helm fail-closed: production + OIDC issuer requires a resolved Redis URL."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

_REPO = Path(__file__).resolve().parents[3]
_CHART = _REPO / "infra" / "deploy" / "helm" / "fraud-stack"
_GEN = _REPO / "infra" / "scripts" / "deploy" / "generate_cloud_values.py"
_CORE_AWS = _CHART / "presets" / "core-on-aws.yaml"


def _helm(extra: list[str]) -> subprocess.CompletedProcess[str]:
    helm = shutil.which("helm")
    if not helm:
        raise unittest.SkipTest("helm is not installed")
    return subprocess.run(
        [helm, "template", "tarka", str(_CHART), *extra],
        cwd=str(_REPO),
        capture_output=True,
        text=True,
    )


class TestHelmOidcRequiresRedis(unittest.TestCase):
    def test_prod_profile_issuer_without_redis_fails_render(self) -> None:
        r = _helm(
            [
                "-f",
                str(_CHART / "values.yaml"),
                "--set",
                "redis.enabled=false",
                "--set",
                "global.externalServices.redis.enabled=false",
                "--set",
                "coreApi.extraEnv.TARKA_DEPLOYMENT_PROFILE=production",
                "--set-string",
                "coreApi.extraEnv.OIDC_ISSUER=https://idp.example.com",
            ]
        )
        self.assertNotEqual(r.returncode, 0, r.stdout)
        self.assertIn("OIDC_ISSUER is set in production but REDIS_URL", r.stderr)

    def test_core_on_aws_issuer_with_placeholder_redis_fails_render(self) -> None:
        r = _helm(
            [
                "-f",
                str(_CORE_AWS),
                "--set-string",
                "coreApi.extraEnv.OIDC_ISSUER=https://idp.example.com",
            ]
        )
        self.assertNotEqual(r.returncode, 0, r.stdout)
        self.assertIn("OIDC_ISSUER is set in production but REDIS_URL", r.stderr)

    def test_empty_issuer_still_templates_default_chart(self) -> None:
        r = _helm(["-f", str(_CHART / "values.yaml")])
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("REDIS_URL", r.stdout)

    def test_prod_on_k8s_with_issuer_and_resolved_redis_templates(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "prod-on-k8s.values.yaml"
            subprocess.run(
                [
                    "python3",
                    str(_GEN),
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
                ],
                cwd=str(_REPO),
                check=True,
                capture_output=True,
                text=True,
            )
            r = _helm(
                [
                    "-f",
                    str(out),
                    "--set-string",
                    "coreApi.extraEnv.OIDC_ISSUER=https://idp.example.com",
                ]
            )
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("https://idp.example.com", r.stdout)


if __name__ == "__main__":
    raise SystemExit(unittest.main())
