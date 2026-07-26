"""Production deployment profile — fail-closed auth / tenant / idempotency checks."""

from __future__ import annotations

from typing import Mapping


def _truthy(raw: str | None) -> bool:
    return (raw or "").strip().lower() in ("1", "true", "yes", "on")


def check_production_env(env: Mapping[str, str]) -> list[str]:
    """Return human-readable errors when *env* is not safe for production.

    Soft-open auth, missing API keys, or evaluate without idempotency requirements fail.
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
    return errors


def assert_production_env(env: Mapping[str, str]) -> None:
    """Raise ``RuntimeError`` if production checks fail."""
    errors = check_production_env(env)
    if errors:
        raise RuntimeError("production profile checks failed: " + "; ".join(errors))


def deployment_profile_is_production(env: Mapping[str, str]) -> bool:
    return (env.get("TARKA_DEPLOYMENT_PROFILE") or "").strip().lower() == "production"
