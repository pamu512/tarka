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


def test_validate_prod_fails_missing_evaluate_idempotency():
    text = (HELM / "validate-prod.yaml").read_text(encoding="utf-8")
    assert "TARKA_EVALUATE_REQUIRE_IDEMPOTENCY_KEY" in text
    assert "same fail-closed rule as production_profile" in text
    idem_at = text.index("TARKA_EVALUATE_REQUIRE_IDEMPOTENCY_KEY must be true in production")
    gate_at = text.index("$prodOnK8s :=")
    assert idem_at < gate_at


def test_core_on_aws_sets_evaluate_idempotency_extra_env():
    preset = ROOT / "infra" / "deploy" / "helm" / "fraud-stack" / "presets" / "core-on-aws.yaml"
    text = preset.read_text(encoding="utf-8")
    assert "TARKA_EVALUATE_REQUIRE_IDEMPOTENCY_KEY" in text
    assert "TARKA_DEPLOYMENT_PROFILE: production" in text


def test_validate_prod_fails_missing_copilot_production_mode():
    """Helm leftover: agent on in prod without COPILOT_PRODUCTION_MODE skipped Python fail-closes."""
    text = (HELM / "validate-prod.yaml").read_text(encoding="utf-8")
    assert (
        "COPILOT_PRODUCTION_MODE must be true in production when investigation-agent is enabled"
        in text
    )
    copilot_at = text.index("COPILOT_PRODUCTION_MODE must be true in production")
    gate_at = text.index("$prodOnK8s :=")
    assert copilot_at < gate_at


def test_prod_presets_set_copilot_production_mode_when_agent_enabled():
    presets = ROOT / "infra" / "deploy" / "helm" / "fraud-stack" / "presets"
    for name in ("prod-on-k8s.yaml", "investigation-on-aws.yaml", "full-on-k8s.yaml"):
        text = (presets / name).read_text(encoding="utf-8")
        assert 'COPILOT_PRODUCTION_MODE: "true"' in text, name


def test_validate_prod_fails_missing_ingest_idempotency():
    text = (HELM / "validate-prod.yaml").read_text(encoding="utf-8")
    assert "INGEST_REQUIRE_IDEMPOTENCY_KEY" in text
    assert "when data-plane is enabled" in text
    ingest_at = text.index("INGEST_REQUIRE_IDEMPOTENCY_KEY must be true in production")
    gate_at = text.index("$prodOnK8s :=")
    assert ingest_at < gate_at


def test_prod_presets_with_data_plane_set_ingest_idempotency():
    presets = ROOT / "infra" / "deploy" / "helm" / "fraud-stack" / "presets"
    for name in ("full-on-k8s.yaml", "investigation-on-aws.yaml", "tenant-binding-enforced.yaml"):
        body = (presets / name).read_text(encoding="utf-8")
        assert 'INGEST_REQUIRE_IDEMPOTENCY_KEY: "true"' in body, name
