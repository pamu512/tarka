from __future__ import annotations
from typing import Any

from fastapi import HTTPException

"""BYOK (bring-your-own-key) contract for connector credentials (Refund Swatter #59 / epic #58)."""
BYOK_POLICY_VERSION = 1

# Keys that imply the platform holds third-party API custody (forbidden under strict BYOK).
_FORBIDDEN_PLATFORM_CUSTODY_KEYS: frozenset[str] = frozenset(
    {
        "platform_api_key",
        "tarka_delegate_secret",
        "shared_master_key",
        "argus_master_token",
    },
)

SECRET_STORAGE_RULES: list[str] = [
    "Tenant connector material MUST be stored only as KMS-envelope ciphertext in IntegrationSecret rows.",
    "Plaintext secrets MUST NOT be written to application logs, audit payloads, or non-vault tables.",
    "Outbound calls MUST load material via vault decrypt in-process; do not forward raw secrets to other services.",
    "Rotation MUST re-wrap ciphertext with tenant-visible key ids (see /v1/vault/rotate).",
]


def default_byok_capabilities() -> dict[str, Any]:
    return {
        "tenant_owned_material": True,
        "platform_custody_forbidden": True,
        "envelope_encryption_required": True,
    }


def enrich_provider(provider: dict[str, Any]) -> dict[str, Any]:
    """Return catalog provider with merged ``byok_capabilities`` (read-only copy)."""
    out = dict(provider)
    caps = dict(default_byok_capabilities())
    extra = provider.get("byok_capabilities")
    if isinstance(extra, dict):
        caps.update({str(k): v for k, v in extra.items()})
    out["byok_capabilities"] = caps
    return out


def validate_install_config(config: dict[str, Any] | None) -> None:
    """Reject configs that declare forbidden platform-custody keys."""
    if not config:
        return
    lowered = {str(k).lower() for k in config}
    hit = sorted(_FORBIDDEN_PLATFORM_CUSTODY_KEYS & lowered)
    if hit:
        raise HTTPException(
            status_code=400,
            detail=f"byok_policy_violation: forbidden platform-custody keys: {', '.join(hit)}",
        )


def policy_document(*, providers: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "schema": "tarka.byok_policy/v1",
        "version": BYOK_POLICY_VERSION,
        "secret_storage_rules": SECRET_STORAGE_RULES,
        "forbidden_platform_custody_keys": sorted(_FORBIDDEN_PLATFORM_CUSTODY_KEYS),
        "providers": [enrich_provider(p) for p in providers],
    }
