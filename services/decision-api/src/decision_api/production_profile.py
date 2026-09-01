"""Production deployment profile — fail-closed auth / tenant / idempotency checks."""

from __future__ import annotations

import json
from typing import Any, Mapping
from urllib.parse import urlparse


def _truthy(raw: str | None) -> bool:
    return (raw or "").strip().lower() in ("1", "true", "yes", "on")


def deployment_profile_is_production(env: Mapping[str, str]) -> bool:
    return (env.get("TARKA_DEPLOYMENT_PROFILE") or "").strip().lower() == "production"


def helm_environment_is_prod(env: Mapping[str, str]) -> bool:
    raw = (
        (env.get("TARKA_HELM_ENVIRONMENT") or env.get("TARKA_ENVIRONMENT") or "")
        .strip()
        .lower()
    )
    return raw == "prod"


def forbids_wildcard_tenant_scope(env: Mapping[str, str]) -> bool:
    """Ban ``*`` API-key tenant scope in production profile or Helm prod."""
    return should_enforce_production_profile(env)


def should_enforce_production_profile(env: Mapping[str, str]) -> bool:
    """Same prod lock as tenant wildcard: profile=production or Helm environment=prod.

    Helm core-on-aws injects ``TARKA_HELM_ENVIRONMENT=prod`` without
    ``TARKA_DEPLOYMENT_PROFILE``. Evaluate idempotency and the rest of
    ``check_production_env`` must still run.
    """
    return deployment_profile_is_production(env) or helm_environment_is_prod(env)


def rust_rule_engine_importable() -> bool:
    try:
        import tarka_rule_engine  # noqa: F401

        return callable(getattr(tarka_rule_engine, "evaluate_json_rules_rust", None))
    except ImportError:
        return False


def _map_has_wildcard(payload: Any) -> bool:
    if not isinstance(payload, dict):
        return False
    for value in payload.values():
        if isinstance(value, str) and value.strip() == "*":
            return True
        if isinstance(value, list) and any(str(item).strip() == "*" for item in value):
            return True
    return False


def check_api_key_tenant_map(env: Mapping[str, str]) -> list[str]:
    """Fail-closed tenant-map checks for production / Helm prod."""
    errors: list[str] = []
    raw = (env.get("API_KEY_TENANT_MAP") or "").strip()
    if not raw:
        return errors
    try:
        payload = json.loads(raw)
    except Exception:
        errors.append("API_KEY_TENANT_MAP is not valid JSON")
        return errors
    if not isinstance(payload, dict):
        errors.append("API_KEY_TENANT_MAP must be a JSON object")
        return errors
    if _map_has_wildcard(payload):
        errors.append(
            "API_KEY_TENANT_MAP must not grant '*' tenant scope in production"
        )
    return errors


def check_sor_not_age_postgres(env: Mapping[str, str]) -> list[str]:
    """SoR DATABASE_URL must not point at the Tarka AGE Hunt sidecar."""
    age_svc = (env.get("TARKA_AGE_POSTGRES_SERVICE") or "").strip()
    if not age_svc:
        return []
    db_url = (env.get("DATABASE_URL") or "").strip()
    if not db_url:
        return []
    # asyncpg URLs may use postgresql+asyncpg:// — normalize for host match
    normalized = db_url.replace("postgresql+asyncpg://", "postgresql://", 1)
    try:
        host = (urlparse(normalized).hostname or "").strip().lower()
    except Exception:
        host = ""
    marker = age_svc.strip().lower()
    if marker and (
        marker in db_url.lower() or marker == host or host.endswith(f".{marker}")
    ):
        return [
            "DATABASE_URL must not point at Tarka AGE Hunt postgres in production "
            f"(split-plane: SoR is buyer Postgres; found AGE service {age_svc!r})"
        ]
    return []


def check_sar_transport_choice(env: Mapping[str, str]) -> list[str]:
    """SAR is off-or-configured — silence is not an accidental miss."""
    mode = (env.get("SAR_TRANSPORT") or "").strip().lower()
    if mode in ("off", "disabled", "0", "false", "no"):
        return []
    host = (env.get("FINCEN_BSA_SFTP_HOST") or "").strip()
    user = (env.get("FINCEN_BSA_SFTP_USER") or "").strip()
    if host and user:
        return []
    return [
        "SAR_TRANSPORT must be 'off' or FINCEN_BSA_SFTP_HOST+FINCEN_BSA_SFTP_USER "
        "must be set in production (silence is not a choice)"
    ]


def check_production_env(
    env: Mapping[str, str],
    *,
    rust_available: bool | None = None,
) -> list[str]:
    """Return human-readable errors when *env* is not safe for production.

    Soft-open auth, missing API keys, or evaluate without idempotency requirements fail.

    ``OIDC_ISSUER`` is intentionally not required: API keys remain the machine
    authentication path. Desk SSO is optional. When the issuer *is* set,
    ``REDIS_URL`` must be a resolved URL (no empty value or ``__`` placeholder)
    — same fail-closed rule as core-api OIDC (no in-process OIDC state fallback).
    Wildcard API-key tenant scope (``*``) is refused.

    Rust ``tarka_rule_engine`` is required unless ``TARKA_ALLOW_PYTHON_RULE_ENGINE``
    is an explicit signed exception. ``RULE_GOVERNANCE_SECRET`` is required.
    SAR must be off or configured. SoR must not use the AGE Hunt sidecar.
    """
    errors: list[str] = []
    if _truthy(env.get("ALLOW_INSECURE_NO_AUTH")):
        errors.append(
            "ALLOW_INSECURE_NO_AUTH must be unset/false in production "
            "(refusing soft-open auth)"
        )
    api_keys = (env.get("API_KEYS") or "").strip()
    if not api_keys:
        errors.append("API_KEYS must be non-empty in production")
    if not _truthy(env.get("TARKA_EVALUATE_REQUIRE_IDEMPOTENCY_KEY")):
        errors.append(
            "TARKA_EVALUATE_REQUIRE_IDEMPOTENCY_KEY must be true in production"
        )
    if not (env.get("RULE_GOVERNANCE_SECRET") or "").strip():
        errors.append("RULE_GOVERNANCE_SECRET must be non-empty in production")
    errors.extend(check_api_key_tenant_map(env))
    errors.extend(check_sar_transport_choice(env))
    errors.extend(check_sor_not_age_postgres(env))
    issuer = (env.get("OIDC_ISSUER") or "").strip()
    if issuer:
        redis_url = (env.get("REDIS_URL") or "").strip()
        if (not redis_url) or ("__" in redis_url):
            errors.append(
                "REDIS_URL is required when OIDC_ISSUER is set in production "
                "(no in-process OIDC state fallback)"
            )
    if not _truthy(env.get("TARKA_ALLOW_PYTHON_RULE_ENGINE")):
        available = (
            rust_rule_engine_importable()
            if rust_available is None
            else bool(rust_available)
        )
        if not available:
            errors.append(
                "tarka_rule_engine (Rust) must be installed in production "
                "(set TARKA_ALLOW_PYTHON_RULE_ENGINE=1 only as a signed exception)"
            )
    return errors


def assert_production_env(
    env: Mapping[str, str],
    *,
    rust_available: bool | None = None,
) -> None:
    """Raise ``RuntimeError`` if production checks fail."""
    errors = check_production_env(env, rust_available=rust_available)
    if errors:
        raise RuntimeError("production profile checks failed: " + "; ".join(errors))
