"""Production deployment profile — fail-closed auth / tenant / idempotency checks."""

from __future__ import annotations

import json
from typing import Any, Mapping


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
    return deployment_profile_is_production(env) or helm_environment_is_prod(env)


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


def check_production_env(env: Mapping[str, str]) -> list[str]:
    """Return human-readable errors when *env* is not safe for production.

    Soft-open auth, missing API keys, or evaluate without idempotency requirements fail.

    ``OIDC_ISSUER`` is intentionally not required: API keys remain the machine
    authentication path. Desk SSO is optional. When the issuer *is* set,
    ``REDIS_URL`` must be a resolved URL (no empty value or ``__`` placeholder)
    — same fail-closed rule as core-api OIDC (no in-process state fallback).
    Wildcard API-key tenant scope (``*``) is refused.
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
    errors.extend(check_api_key_tenant_map(env))
    issuer = (env.get("OIDC_ISSUER") or "").strip()
    if issuer:
        redis_url = (env.get("REDIS_URL") or "").strip()
        if (not redis_url) or ("__" in redis_url):
            errors.append(
                "REDIS_URL is required when OIDC_ISSUER is set in production "
                "(no in-process OIDC state fallback)"
            )
    return errors


def assert_production_env(env: Mapping[str, str]) -> None:
    """Raise ``RuntimeError`` if production checks fail."""
    errors = check_production_env(env)
    if errors:
        raise RuntimeError("production profile checks failed: " + "; ".join(errors))
