"""Production fail-closed profile checks."""

from pathlib import Path

import pytest

from decision_api.production_profile import (
    assert_production_env,
    check_production_env,
    deployment_profile_is_production,
    forbids_wildcard_tenant_scope,
    should_enforce_production_profile,
)


def test_ok_env_passes():
    assert (
        check_production_env(
            {
                "API_KEYS": "secret",
                "TARKA_EVALUATE_REQUIRE_IDEMPOTENCY_KEY": "true",
                "ALLOW_INSECURE_NO_AUTH": "false",
            }
        )
        == []
    )


def test_insecure_auth_fails():
    errs = check_production_env(
        {
            "API_KEYS": "secret",
            "TARKA_EVALUATE_REQUIRE_IDEMPOTENCY_KEY": "true",
            "ALLOW_INSECURE_NO_AUTH": "true",
        }
    )
    assert any("ALLOW_INSECURE_NO_AUTH" in e for e in errs)


def test_missing_keys_and_idempotency_fail():
    errs = check_production_env({})
    assert any("API_KEYS" in e for e in errs)
    assert any("IDEMPOTENCY" in e for e in errs)


def test_assert_raises():
    with pytest.raises(RuntimeError, match="production profile"):
        assert_production_env({"ALLOW_INSECURE_NO_AUTH": "1"})


def test_deployment_profile_flag():
    assert deployment_profile_is_production({"TARKA_DEPLOYMENT_PROFILE": "production"})
    assert not deployment_profile_is_production({"TARKA_DEPLOYMENT_PROFILE": "dev"})


def test_production_profile_does_not_require_oidc_issuer():
    """API keys remain the machine path; empty OIDC_ISSUER is production-safe."""
    errs = check_production_env(
        {
            "API_KEYS": "secret",
            "TARKA_EVALUATE_REQUIRE_IDEMPOTENCY_KEY": "true",
            "ALLOW_INSECURE_NO_AUTH": "false",
        }
    )
    assert errs == []
    assert not any(
        "OIDC" in e
        for e in check_production_env(
            {
                "API_KEYS": "secret",
                "TARKA_EVALUATE_REQUIRE_IDEMPOTENCY_KEY": "true",
                "OIDC_ISSUER": "",
            }
        )
    )


def test_wildcard_tenant_scope_rejected_in_production_profile():
    errs = check_production_env(
        {
            "API_KEYS": "secret",
            "TARKA_EVALUATE_REQUIRE_IDEMPOTENCY_KEY": "true",
            "API_KEY_TENANT_MAP": '{"k1": "*"}',
        }
    )
    assert any("*" in e for e in errs)


def test_valid_tenant_map_passes_production_profile():
    assert (
        check_production_env(
            {
                "API_KEYS": "secret",
                "TARKA_EVALUATE_REQUIRE_IDEMPOTENCY_KEY": "true",
                "API_KEY_TENANT_MAP": '{"k1": "tenant_alpha"}',
            }
        )
        == []
    )


def test_forbids_wildcard_for_profile_or_helm_prod():
    assert forbids_wildcard_tenant_scope({"TARKA_DEPLOYMENT_PROFILE": "production"})
    assert forbids_wildcard_tenant_scope({"TARKA_HELM_ENVIRONMENT": "prod"})
    assert not forbids_wildcard_tenant_scope({"TARKA_DEPLOYMENT_PROFILE": "dev"})


def test_issuer_without_redis_fails():
    errs = check_production_env(
        {
            "API_KEYS": "secret",
            "TARKA_EVALUATE_REQUIRE_IDEMPOTENCY_KEY": "true",
            "OIDC_ISSUER": "https://idp.example.com",
        }
    )
    assert any("REDIS_URL" in e and "OIDC_ISSUER" in e for e in errs)


def test_issuer_with_redis_placeholder_fails():
    errs = check_production_env(
        {
            "API_KEYS": "secret",
            "TARKA_EVALUATE_REQUIRE_IDEMPOTENCY_KEY": "true",
            "OIDC_ISSUER": "https://idp.example.com",
            "REDIS_URL": "__REDIS_URL__",
        }
    )
    assert any("REDIS_URL" in e for e in errs)


def test_issuer_with_redis_passes():
    assert (
        check_production_env(
            {
                "API_KEYS": "secret",
                "TARKA_EVALUATE_REQUIRE_IDEMPOTENCY_KEY": "true",
                "OIDC_ISSUER": "https://idp.example.com",
                "REDIS_URL": "rediss://elasticache:6379/0",
            }
        )
        == []
    )


def test_should_enforce_production_profile_includes_helm_prod():
    """core-on-aws leftover: Helm env=prod must run the same checks as profile=production."""
    assert should_enforce_production_profile({"TARKA_HELM_ENVIRONMENT": "prod"})
    assert should_enforce_production_profile({"TARKA_DEPLOYMENT_PROFILE": "production"})
    assert not should_enforce_production_profile({"TARKA_HELM_ENVIRONMENT": "dev"})
    errs = check_production_env(
        {
            "API_KEYS": "secret",
            "ALLOW_INSECURE_NO_AUTH": "false",
            "TARKA_HELM_ENVIRONMENT": "prod",
        }
    )
    assert any("IDEMPOTENCY" in e for e in errs)


def test_compose_production_hardening_sets_deployment_profile():
    """Overlay leftover: knobs without TARKA_DEPLOYMENT_PROFILE skipped Python fail-closes."""
    overlay = (
        Path(__file__).resolve().parents[3]
        / "infra"
        / "deploy"
        / "docker-compose.production-hardening.yml"
    ).read_text(encoding="utf-8")
    assert overlay.count("TARKA_DEPLOYMENT_PROFILE: production") >= 4
    for needle in (
        "core-api:\n    environment:\n      TARKA_DEPLOYMENT_PROFILE: production",
        "integration-ingress:\n    environment:\n      TARKA_DEPLOYMENT_PROFILE: production",
        "graph-service:\n    environment:\n      TARKA_DEPLOYMENT_PROFILE: production",
        "data-plane:\n    environment:\n      TARKA_DEPLOYMENT_PROFILE: production",
    ):
        assert needle in overlay

def test_compose_production_hardening_sets_case_api_production_mode():
    """Overlay leftover: profile on core-api skipped case-api sqlite/evidence fail-close."""
    overlay = (
        Path(__file__).resolve().parents[3]
        / "infra"
        / "deploy"
        / "docker-compose.production-hardening.yml"
    ).read_text(encoding="utf-8")
    assert 'CASE_API_PRODUCTION_MODE: "true"' in overlay
