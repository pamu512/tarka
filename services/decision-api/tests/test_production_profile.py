"""Production fail-closed profile checks."""

from pathlib import Path

import pytest

from decision_api.production_profile import (
    assert_production_env,
    check_production_env,
    check_sar_transport_choice,
    check_sor_not_age_postgres,
    deployment_profile_is_production,
    forbids_wildcard_tenant_scope,
    should_enforce_production_profile,
)


def _ok(**extra: str) -> dict[str, str]:
    base = {
        "API_KEYS": "secret",
        "TARKA_EVALUATE_REQUIRE_IDEMPOTENCY_KEY": "true",
        "ALLOW_INSECURE_NO_AUTH": "false",
        "RULE_GOVERNANCE_SECRET": "gov-secret",
        "SAR_TRANSPORT": "off",
    }
    base.update(extra)
    return base


def test_ok_env_passes():
    assert check_production_env(_ok(), rust_available=True) == []


def test_insecure_auth_fails():
    errs = check_production_env(_ok(ALLOW_INSECURE_NO_AUTH="true"), rust_available=True)
    assert any("ALLOW_INSECURE_NO_AUTH" in e for e in errs)


def test_missing_keys_and_idempotency_fail():
    errs = check_production_env({}, rust_available=True)
    assert any("API_KEYS" in e for e in errs)
    assert any("IDEMPOTENCY" in e for e in errs)
    assert any("RULE_GOVERNANCE_SECRET" in e for e in errs)


def test_assert_raises():
    with pytest.raises(RuntimeError, match="production profile"):
        assert_production_env(
            {"ALLOW_INSECURE_NO_AUTH": "1"}, rust_available=True
        )


def test_deployment_profile_flag():
    assert deployment_profile_is_production({"TARKA_DEPLOYMENT_PROFILE": "production"})
    assert not deployment_profile_is_production({"TARKA_DEPLOYMENT_PROFILE": "dev"})


def test_production_profile_does_not_require_oidc_issuer():
    """API keys remain the machine path; empty OIDC_ISSUER is production-safe."""
    errs = check_production_env(_ok(), rust_available=True)
    assert errs == []
    assert not any(
        "OIDC" in e
        for e in check_production_env(_ok(OIDC_ISSUER=""), rust_available=True)
    )


def test_wildcard_tenant_scope_rejected_in_production_profile():
    errs = check_production_env(
        _ok(API_KEY_TENANT_MAP='{"k1": "*"}'),
        rust_available=True,
    )
    assert any("*" in e for e in errs)


def test_valid_tenant_map_passes_production_profile():
    assert (
        check_production_env(
            _ok(API_KEY_TENANT_MAP='{"k1": "tenant_alpha"}'),
            rust_available=True,
        )
        == []
    )


def test_forbids_wildcard_for_profile_or_helm_prod():
    assert forbids_wildcard_tenant_scope({"TARKA_DEPLOYMENT_PROFILE": "production"})
    assert forbids_wildcard_tenant_scope({"TARKA_HELM_ENVIRONMENT": "prod"})
    assert not forbids_wildcard_tenant_scope({"TARKA_DEPLOYMENT_PROFILE": "dev"})


def test_issuer_without_redis_fails():
    errs = check_production_env(
        _ok(OIDC_ISSUER="https://idp.example.com"),
        rust_available=True,
    )
    assert any("REDIS_URL" in e and "OIDC_ISSUER" in e for e in errs)


def test_issuer_with_redis_placeholder_fails():
    errs = check_production_env(
        _ok(
            OIDC_ISSUER="https://idp.example.com",
            REDIS_URL="__REDIS_URL__",
        ),
        rust_available=True,
    )
    assert any("REDIS_URL" in e for e in errs)


def test_issuer_with_redis_passes():
    assert (
        check_production_env(
            _ok(
                OIDC_ISSUER="https://idp.example.com",
                REDIS_URL="rediss://elasticache:6379/0",
            ),
            rust_available=True,
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
            "RULE_GOVERNANCE_SECRET": "gov",
            "SAR_TRANSPORT": "off",
        },
        rust_available=True,
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


def test_rust_engine_required_unless_signed_exception():
    errs = check_production_env(_ok(), rust_available=False)
    assert any("tarka_rule_engine" in e for e in errs)
    assert (
        check_production_env(
            _ok(TARKA_ALLOW_PYTHON_RULE_ENGINE="1"),
            rust_available=False,
        )
        == []
    )


def test_rule_governance_secret_required():
    env = _ok()
    del env["RULE_GOVERNANCE_SECRET"]
    errs = check_production_env(env, rust_available=True)
    assert any("RULE_GOVERNANCE_SECRET" in e for e in errs)


def test_sar_transport_off_or_configured():
    assert check_sar_transport_choice({"SAR_TRANSPORT": "off"}) == []
    assert (
        check_sar_transport_choice(
            {
                "FINCEN_BSA_SFTP_HOST": "sftp.example.com",
                "FINCEN_BSA_SFTP_USER": "bsa",
            }
        )
        == []
    )
    errs = check_sar_transport_choice({})
    assert any("SAR_TRANSPORT" in e for e in errs)
    assert (
        check_production_env(
            _ok(
                SAR_TRANSPORT="",
                FINCEN_BSA_SFTP_HOST="sftp.example.com",
                FINCEN_BSA_SFTP_USER="bsa",
            ),
            rust_available=True,
        )
        == []
    )


def test_sor_must_not_point_at_age_sidecar():
    errs = check_sor_not_age_postgres(
        {
            "TARKA_AGE_POSTGRES_SERVICE": "tarka-age-postgres",
            "DATABASE_URL": "postgresql+asyncpg://fraud:fraud@tarka-age-postgres:5432/fraud",
        }
    )
    assert any("AGE" in e for e in errs)
    assert (
        check_sor_not_age_postgres(
            {
                "TARKA_AGE_POSTGRES_SERVICE": "tarka-age-postgres",
                "DATABASE_URL": "postgresql+asyncpg://u:p@buyer-rds:5432/fraud",
            }
        )
        == []
    )
