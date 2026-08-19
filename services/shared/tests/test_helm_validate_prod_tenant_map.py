from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
HELM = ROOT / "infra" / "deploy" / "helm" / "fraud-stack" / "templates"


def test_validate_prod_fails_if_tenant_map_optional():
    text = (HELM / "validate-prod.yaml").read_text(encoding="utf-8")
    assert "API_KEY_TENANT_MAP" in text
    assert "optional" in text
    assert "fail" in text


def test_core_api_omits_optional_tenant_map_in_prod():
    text = (HELM / "core-api.yaml").read_text(encoding="utf-8")
    assert "tarka.apiKeyTenantMapOptional" in text
    assert "API_KEY_TENANT_MAP" in text


def test_helpers_tenant_map_optional_false_in_prod():
    text = (HELM / "_helpers.tpl").read_text(encoding="utf-8")
    assert "tarka.apiKeyTenantMapOptional" in text
    assert 'eq (default "dev" .Values.global.environment) "prod"' in text


def test_validate_prod_fails_issuer_without_redis():
    text = (HELM / "validate-prod.yaml").read_text(encoding="utf-8")
    assert "OIDC_ISSUER" in text
    assert "REDIS_URL" in text
    assert "no in-process OIDC state fallback" in text
    assert 'hasKey $extraEnv "OIDC_ISSUER"' in text
    # Must run outside the prod-on-k8s PDB+HPA gate (core-on-aws leftover).
    oidc_at = text.index("OIDC_ISSUER is set in production but REDIS_URL")
    gate_at = text.index("$prodOnK8s :=")
    assert oidc_at < gate_at
