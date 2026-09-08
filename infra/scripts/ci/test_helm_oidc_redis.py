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
                "--set",
                "coreApi.extraEnv.TARKA_EVALUATE_REQUIRE_IDEMPOTENCY_KEY=true",
                "--set",
                "dataPlane.extraEnv.INGEST_REQUIRE_IDEMPOTENCY_KEY=true",
                "--set",
                "coreApi.extraEnv.CASE_API_PRODUCTION_MODE=true",
                "--set",
                "coreApi.extraEnv.SAR_TRANSPORT=off",
                "--set-string",
                "coreApi.extraEnv.OIDC_ISSUER=https://idp.example.com",
            ]
        )
        self.assertNotEqual(r.returncode, 0, r.stdout)
        self.assertIn("OIDC_ISSUER is set in production but REDIS_URL", r.stderr)

    def test_first_class_oidc_issuer_without_redis_fails_render(self) -> None:
        """SoT is coreApi.oidc.issuer — extraEnv is leftover fallback only."""
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
                "--set",
                "coreApi.extraEnv.TARKA_EVALUATE_REQUIRE_IDEMPOTENCY_KEY=true",
                "--set",
                "dataPlane.extraEnv.INGEST_REQUIRE_IDEMPOTENCY_KEY=true",
                "--set",
                "coreApi.extraEnv.CASE_API_PRODUCTION_MODE=true",
                "--set",
                "coreApi.extraEnv.SAR_TRANSPORT=off",
                "--set-string",
                "coreApi.oidc.issuer=https://idp.example.com",
            ]
        )
        self.assertNotEqual(r.returncode, 0, r.stdout)
        self.assertIn("OIDC_ISSUER is set in production but REDIS_URL", r.stderr)

    def test_first_class_oidc_values_emit_env(self) -> None:
        r = _helm(
            [
                "-f",
                str(_CHART / "values.yaml"),
                "--set-string",
                "coreApi.oidc.issuer=https://idp.example.com",
                "--set-string",
                "coreApi.oidc.audience=desk",
                "--set-string",
                "coreApi.oidc.jwksUrl=https://idp.example.com/jwks",
                "--set-string",
                "coreApi.oidc.rolesClaim=tarka_roles",
            ]
        )
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("name: OIDC_ISSUER", r.stdout)
        self.assertIn("https://idp.example.com", r.stdout)
        self.assertIn("name: OIDC_AUDIENCE", r.stdout)
        self.assertIn("desk", r.stdout)
        self.assertIn("name: OIDC_JWKS_URL", r.stdout)
        self.assertIn("https://idp.example.com/jwks", r.stdout)
        self.assertIn("name: OIDC_ROLES_CLAIM", r.stdout)
        self.assertIn("tarka_roles", r.stdout)

    def test_first_class_oidc_wins_over_extra_env(self) -> None:
        r = _helm(
            [
                "-f",
                str(_CHART / "values.yaml"),
                "--set-string",
                "coreApi.oidc.issuer=https://values-sot.example.com",
                "--set-string",
                "coreApi.oidc.audience=from-values",
                "--set-string",
                "coreApi.oidc.jwksUrl=https://values-sot.example.com/jwks",
                "--set-string",
                "coreApi.oidc.rolesClaim=from_values",
                "--set-string",
                "coreApi.extraEnv.OIDC_ISSUER=https://extraenv-lore.example.com",
                "--set-string",
                "coreApi.extraEnv.OIDC_AUDIENCE=from-extra",
                "--set-string",
                "coreApi.extraEnv.OIDC_JWKS_URL=https://extraenv-lore.example.com/jwks",
                "--set-string",
                "coreApi.extraEnv.OIDC_ROLES_CLAIM=from_extra",
            ]
        )
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("https://values-sot.example.com", r.stdout)
        self.assertNotIn("https://extraenv-lore.example.com", r.stdout)
        self.assertIn("from-values", r.stdout)
        self.assertNotIn("from-extra", r.stdout)
        self.assertIn("from_values", r.stdout)
        self.assertNotIn("from_extra", r.stdout)

    def test_prod_on_k8s_preset_uses_first_class_oidc_not_extra_env(self) -> None:
        text = (_CHART / "presets" / "prod-on-k8s.yaml").read_text(encoding="utf-8")
        self.assertIn("oidc:", text)
        self.assertIn("jwksUrl:", text)
        self.assertIn("rolesClaim:", text)
        self.assertNotIn("OIDC is not a first-class", text)
        extra = text.split("extraEnv:", 1)[1]
        self.assertNotIn("OIDC_ISSUER", extra)
        self.assertNotIn("OIDC_AUDIENCE", extra)
        self.assertNotIn("OIDC_JWKS_URL", extra)
        self.assertNotIn("OIDC_ROLES_CLAIM", extra)

    def test_prod_on_k8s_empty_issuer_is_api_key_path(self) -> None:
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
                    "--allow-empty-digest",
                    "--output",
                    str(out),
                ],
                cwd=str(_REPO),
                check=True,
                capture_output=True,
                text=True,
            )
            r = _helm(["-f", str(out)])
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn("name: OIDC_ISSUER", r.stdout)
        self.assertNotIn("allow-egress-https", r.stdout)

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
        # Empty coreApi.oidc.issuer = API-key machine path (no OIDC env leaked).
        self.assertNotIn("name: OIDC_ISSUER", r.stdout)
        self.assertNotIn("name: OIDC_JWKS_URL", r.stdout)
        self.assertNotIn("name: OIDC_ROLES_CLAIM", r.stdout)

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
                    "--allow-empty-digest",
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
                    "coreApi.oidc.issuer=https://idp.example.com",
                ]
            )
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("https://idp.example.com", r.stdout)
        self.assertIn("name: OIDC_ISSUER", r.stdout)
        self.assertIn("allow-egress-https", r.stdout)

    def test_environment_prod_without_idempotency_fails_render(self) -> None:
        r = _helm(
            [
                "-f",
                str(_CHART / "values.yaml"),
                "--set",
                "global.environment=prod",
                "--set",
                "coreApi.extraEnv.SAR_TRANSPORT=off",
            ]
        )
        self.assertNotEqual(r.returncode, 0, r.stdout)
        self.assertIn("TARKA_EVALUATE_REQUIRE_IDEMPOTENCY_KEY", r.stderr)

    def test_core_on_aws_renders_evaluate_idempotency_true(self) -> None:
        r = _helm(["-f", str(_CORE_AWS)])
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("TARKA_EVALUATE_REQUIRE_IDEMPOTENCY_KEY", r.stdout)
        self.assertIn("true", r.stdout)

    def test_environment_prod_agent_without_copilot_mode_fails_render(self) -> None:
        r = _helm(
            [
                "-f",
                str(_CHART / "values.yaml"),
                "--set",
                "global.environment=prod",
                "--set",
                "coreApi.extraEnv.TARKA_EVALUATE_REQUIRE_IDEMPOTENCY_KEY=true",
                "--set",
                "coreApi.extraEnv.CASE_API_PRODUCTION_MODE=true",
                "--set",
                "coreApi.extraEnv.SAR_TRANSPORT=off",
                "--set",
                "investigationAgent.enabled=true",
            ]
        )
        self.assertNotEqual(r.returncode, 0, r.stdout)
        self.assertIn("COPILOT_PRODUCTION_MODE", r.stderr)

    def test_prod_on_k8s_renders_copilot_production_mode(self) -> None:
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
                    "--allow-empty-digest",
                    "--output",
                    str(out),
                ],
                cwd=str(_REPO),
                check=True,
                capture_output=True,
                text=True,
            )
            r = _helm(["-f", str(out), "--set", "global.appSecretsName=tarka-app-secrets"])
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("COPILOT_PRODUCTION_MODE", r.stdout)
        self.assertIn("name: API_KEYS", r.stdout)

    def test_prod_profile_idempotency_false_fails_render(self) -> None:
        r = _helm(
            [
                "-f",
                str(_CHART / "values.yaml"),
                "--set",
                "coreApi.extraEnv.TARKA_DEPLOYMENT_PROFILE=production",
                "--set",
                "coreApi.extraEnv.TARKA_EVALUATE_REQUIRE_IDEMPOTENCY_KEY=false",
                "--set",
                "coreApi.extraEnv.SAR_TRANSPORT=off",
            ]
        )
        self.assertNotEqual(r.returncode, 0, r.stdout)
        self.assertIn("TARKA_EVALUATE_REQUIRE_IDEMPOTENCY_KEY", r.stderr)

    def test_environment_prod_without_case_api_production_mode_fails_render(self) -> None:
        r = _helm(
            [
                "-f",
                str(_CHART / "values.yaml"),
                "--set",
                "global.environment=prod",
                "--set",
                "coreApi.extraEnv.TARKA_EVALUATE_REQUIRE_IDEMPOTENCY_KEY=true",
                "--set",
                "coreApi.extraEnv.SAR_TRANSPORT=off",
            ]
        )
        self.assertNotEqual(r.returncode, 0, r.stdout)
        self.assertIn("CASE_API_PRODUCTION_MODE", r.stderr)

    def test_core_on_aws_renders_case_api_production_mode(self) -> None:
        r = _helm(["-f", str(_CORE_AWS)])
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("CASE_API_PRODUCTION_MODE", r.stdout)

    def test_environment_prod_without_ingest_idempotency_fails_render(self) -> None:
        r = _helm(
            [
                "-f",
                str(_CHART / "values.yaml"),
                "--set",
                "global.environment=prod",
                "--set",
                "coreApi.extraEnv.TARKA_EVALUATE_REQUIRE_IDEMPOTENCY_KEY=true",
                "--set",
                "coreApi.extraEnv.CASE_API_PRODUCTION_MODE=true",
                "--set",
                "coreApi.extraEnv.SAR_TRANSPORT=off",
            ]
        )
        self.assertNotEqual(r.returncode, 0, r.stdout)
        self.assertIn("INGEST_REQUIRE_IDEMPOTENCY_KEY", r.stderr)

    def test_full_on_k8s_renders_ingest_idempotency_true(self) -> None:
        r = _helm(["-f", str(_CHART / "presets" / "full-on-k8s.yaml")])
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("INGEST_REQUIRE_IDEMPOTENCY_KEY", r.stdout)

    def test_enterprise_desk_templates_age_and_graph(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "enterprise-desk.values.yaml"
            subprocess.run(
                [
                    "python3",
                    str(_GEN),
                    "--preset",
                    "enterprise-desk-on-k8s",
                    "--image-registry",
                    "registry.example.com/tarka",
                    "--db-url",
                    "postgresql+asyncpg://fraud:pw@rds.internal:5432/fraud",
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
                    "--set",
                    "global.appSecretsName=tarka-app-secrets",
                ]
            )
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("age-postgres", r.stdout)
        self.assertIn("graph-service", r.stdout)
        self.assertIn("TARKA_AGE_POSTGRES_SERVICE", r.stdout)
        self.assertIn("RULE_FORCE_LIVE_TWO_PERSON", r.stdout)
        self.assertIn("RULE_GOVERNANCE_SECRET", r.stdout)
        self.assertIn("AGE_POSTGRES_PASSWORD", r.stdout)
        self.assertIn("AGE_DATABASE_URL", r.stdout)
        self.assertNotIn(":fraud@", r.stdout)
        preset = (_CHART / "presets" / "enterprise-desk-on-k8s.yaml").read_text(encoding="utf-8")
        self.assertNotIn("password: fraud", preset)
        self.assertNotIn("name: OIDC_ISSUER", r.stdout)


if __name__ == "__main__":
    raise SystemExit(unittest.main())
