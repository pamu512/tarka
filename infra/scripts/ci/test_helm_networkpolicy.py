#!/usr/bin/env python3
"""Helm NetworkPolicy gate: default chart emits none; environment=prod emits default-deny + allows."""

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


def _named_policy(rendered: str, name: str) -> str:
    for doc in _documents(rendered):
        if "\nkind: NetworkPolicy\n" in f"\n{doc}\n" and f"\n  name: {name}\n" in f"\n{doc}\n":
            return doc
    raise AssertionError(f"NetworkPolicy {name!r} missing from render")


def _policy_names(rendered: str) -> list[str]:
    names: list[str] = []
    current_kind = ""
    for raw in rendered.splitlines():
        line = raw.rstrip()
        if line.startswith("kind:"):
            current_kind = line.split(":", 1)[1].strip()
        elif current_kind == "NetworkPolicy" and line.startswith("  name:"):
            names.append(line.split(":", 1)[1].strip())
            current_kind = ""
    return names


def _render_prod_on_k8s() -> str:
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
                "--allow-empty-digest",
                "--output",
                str(out),
            ],
            cwd=str(_REPO),
            capture_output=True,
            text=True,
        )
        if gen.returncode != 0:
            raise AssertionError(gen.stderr + gen.stdout)
        return _helm("-f", str(out))


class TestHelmNetworkPolicy(unittest.TestCase):
    def test_default_values_emit_no_networkpolicy(self) -> None:
        rendered = _helm("-f", str(_CHART / "values.yaml"))
        self.assertNotIn("kind: NetworkPolicy", rendered)
        self.assertEqual(_policy_names(rendered), [])

    def test_environment_prod_emits_default_deny_and_allows(self) -> None:
        rendered = _helm(
            "--set",
            "global.environment=prod",
            "--set",
            "coreApi.extraEnv.TARKA_EVALUATE_REQUIRE_IDEMPOTENCY_KEY=true",
            "--set",
            "coreApi.extraEnv.CASE_API_PRODUCTION_MODE=true",
            "--set",
            "coreApi.extraEnv.SAR_TRANSPORT=off",
            "--set",
            "dataPlane.extraEnv.INGEST_REQUIRE_IDEMPOTENCY_KEY=true",
        )
        names = _policy_names(rendered)
        self.assertIn("tarka-tarka-default-deny", names)
        self.assertIn("tarka-tarka-allow-dns", names)
        self.assertIn("tarka-tarka-allow-same-namespace", names)
        self.assertIn("tarka-tarka-allow-frontend-apis", names)
        self.assertIn("tarka-tarka-allow-core-api-datastores", names)
        self.assertIn("tarka-tarka-allow-ingress-frontend", names)
        self.assertIn("tarka-tarka-allow-ingress-core-api", names)
        self.assertNotIn("tarka-tarka-allow-egress-external-data", names)
        self.assertNotIn("tarka-tarka-allow-egress-https", names)
        self.assertIn("k8s-app: kube-dns", rendered)
        self.assertIn("port: 8000", rendered)
        deny = rendered.split("name: tarka-tarka-default-deny", 1)[1].split("---", 1)[0]
        self.assertIn("Ingress", deny)
        self.assertIn("Egress", deny)

    def test_prod_on_k8s_preset_emits_external_and_oidc_egress(self) -> None:
        rendered = _render_prod_on_k8s()
        names = _policy_names(rendered)
        self.assertIn("tarka-tarka-default-deny", names)
        self.assertIn("tarka-tarka-allow-dns", names)
        self.assertIn("tarka-tarka-allow-same-namespace", names)
        self.assertIn("tarka-tarka-allow-egress-external-data", names)
        self.assertNotIn("tarka-tarka-allow-egress-https", names)
        self.assertIn("tarka-tarka-allow-ingress-core-api", names)
        self.assertIn("tarka-tarka-allow-ingress-signal-api", names)
        self.assertNotIn("tarka-tarka-allow-frontend-apis", names)
        self.assertNotIn("tarka-tarka-allow-core-api-datastores", names)
        self.assertIn("port: 5432", rendered)
        self.assertIn("port: 6379", rendered)
        self.assertNotIn("port: 443", rendered)

    def test_prod_on_k8s_first_class_issuer_emits_https_egress(self) -> None:
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
                    "--allow-empty-digest",
                    "--output",
                    str(out),
                ],
                cwd=str(_REPO),
                capture_output=True,
                text=True,
            )
            self.assertEqual(gen.returncode, 0, msg=gen.stderr + gen.stdout)
            rendered = _helm(
                "-f",
                str(out),
                "--set",
                "coreApi.oidc.issuer=https://idp.example.com",
                "--set",
                "coreApi.oidc.jwksUrl=https://idp.example.com/jwks",
            )
        names = _policy_names(rendered)
        self.assertIn("tarka-tarka-allow-egress-https", names)
        self.assertIn("port: 443", rendered)

    def test_prod_on_k8s_core_api_path_is_covered(self) -> None:
        """Ingress + scrape port for core-api evaluate stay open under default-deny."""
        rendered = _render_prod_on_k8s()
        ingress = _named_policy(rendered, "tarka-tarka-allow-ingress-core-api")
        self.assertIn("app: tarka-tarka-core-api", ingress)
        self.assertIn("port: 8000", ingress)
        self.assertIn("Ingress", ingress)
        deny = _named_policy(rendered, "tarka-tarka-default-deny")
        self.assertIn("Ingress", deny)
        self.assertIn("Egress", deny)
        self.assertIn("kind: ServiceMonitor", rendered)
        self.assertIn("tarka-tarka-core-api", rendered)

    def test_lite_on_k8s_emits_no_networkpolicy(self) -> None:
        rendered = _helm("-f", str(_CHART / "presets" / "lite-on-k8s.yaml"))
        self.assertNotIn("kind: NetworkPolicy", rendered)
        self.assertEqual(_policy_names(rendered), [])

    def test_production_profile_without_environment_emits(self) -> None:
        rendered = _helm(
            "--set",
            "coreApi.extraEnv.TARKA_DEPLOYMENT_PROFILE=production",
            "--set",
            "coreApi.extraEnv.TARKA_EVALUATE_REQUIRE_IDEMPOTENCY_KEY=true",
            "--set",
            "coreApi.extraEnv.CASE_API_PRODUCTION_MODE=true",
            "--set",
            "coreApi.extraEnv.SAR_TRANSPORT=off",
            "--set",
            "dataPlane.extraEnv.INGEST_REQUIRE_IDEMPOTENCY_KEY=true",
        )
        names = _policy_names(rendered)
        self.assertIn("tarka-tarka-default-deny", names)
        self.assertIn("tarka-tarka-allow-ingress-core-api", names)

    def test_explicit_opt_out_suppresses_networkpolicy(self) -> None:
        rendered = _helm(
            "--set",
            "global.environment=prod",
            "--set",
            "global.networkPolicy.enabled=false",
            "--set",
            "coreApi.extraEnv.TARKA_EVALUATE_REQUIRE_IDEMPOTENCY_KEY=true",
            "--set",
            "coreApi.extraEnv.CASE_API_PRODUCTION_MODE=true",
            "--set",
            "coreApi.extraEnv.SAR_TRANSPORT=off",
            "--set",
            "dataPlane.extraEnv.INGEST_REQUIRE_IDEMPOTENCY_KEY=true",
        )
        self.assertNotIn("kind: NetworkPolicy", rendered)
        self.assertEqual(_policy_names(rendered), [])


if __name__ == "__main__":
    raise SystemExit(unittest.main())
