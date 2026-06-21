from __future__ import annotations

import logging
import os

log = logging.getLogger(__name__)


def validate_runtime_auth_config(service_name: str) -> list[str]:
    """Validate minimal auth/runtime safety configuration.

    Returns warning strings; never raises to avoid breaking local dev boot.
    """
    warnings: list[str] = []
    api_keys = (os.environ.get("API_KEYS") or "").strip()
    allow_insecure = (os.environ.get("ALLOW_INSECURE_NO_AUTH") or "false").strip().lower() == "true"

    if not api_keys and not allow_insecure:
        warnings.append(
            f"{service_name}: API_KEYS is empty and ALLOW_INSECURE_NO_AUTH is false; "
            "service may fail closed for protected routes."
        )
    if allow_insecure:
        warnings.append(
            f"{service_name}: ALLOW_INSECURE_NO_AUTH=true (development mode). "
            "Disable in production."
        )
    return warnings


def log_runtime_warnings(service_name: str) -> None:
    for msg in validate_runtime_auth_config(service_name):
        log.warning(msg)
