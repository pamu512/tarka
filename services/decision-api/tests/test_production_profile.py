"""Production fail-closed profile checks."""

import pytest

from decision_api.production_profile import (
    assert_production_env,
    check_production_env,
    deployment_profile_is_production,
    forbids_wildcard_tenant_scope,
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
