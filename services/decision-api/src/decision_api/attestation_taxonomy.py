from __future__ import annotations
from typing import Any

"""Shared mobile attestation normalization (Android Play Integrity + iOS App Attest).

See docs/docs/guides/mobile-attestation-taxonomy.md for the human-readable contract.
"""
ATTESTATION_SCHEMA_VERSION = 1

_CANONICAL_PROVIDERS = frozenset({"play_integrity", "app_attest"})
_FAILURE_REASONS = frozenset(
    {
        "client_error",
        "token_unavailable",
        "challenge_failed",
        "integrity_api_error",
        "attest_not_supported",
    },
)  # token_unavailable: obtained without token body
_CONFIDENCE_TIERS = frozenset({"none", "low", "medium", "high"})


def normalize_attestation_object(att: dict[str, Any] | None, *, platform: str) -> dict[str, Any] | None:
    """Return a copy with canonical provider, status, confidence_tier, failure_reason, schema version."""
    if not att:
        return None
    out: dict[str, Any] = dict(att)
    plat = (platform or "web").strip().lower() or "web"
    raw_provider = str(out.get("provider", "") or "").strip().lower()
    if raw_provider in ("google_play_integrity", "playintegrity"):
        raw_provider = "play_integrity"
    if raw_provider in ("apple_app_attest", "devicecheck", "appattest"):
        raw_provider = "app_attest"
    if raw_provider in _CANONICAL_PROVIDERS:
        out["provider"] = raw_provider
    elif raw_provider:
        out["provider"] = raw_provider
    elif plat == "android":
        out["provider"] = "play_integrity"
    elif plat == "ios":
        out["provider"] = "app_attest"
    else:
        out["provider"] = "unknown"

    token = str(out.get("token", "") or "").strip()
    has_token = len(token) > 0

    status = str(out.get("status", "") or "").strip().lower()
    if not status:
        if has_token:
            status = "obtained"
        elif out["provider"] in _CANONICAL_PROVIDERS:
            status = "failed"
        else:
            status = "absent"

    if status == "obtained" and not has_token:
        status = "failed"

    out["status"] = status

    ftier = str(out.get("confidence_tier", "") or "").strip().lower()
    if ftier not in _CONFIDENCE_TIERS:
        ftier = ""
    if not ftier:
        if status == "obtained":
            ftier = "medium"
        else:
            ftier = "none"
    out["confidence_tier"] = ftier

    fail = str(out.get("failure_reason", "") or "").strip().lower()
    if status in ("failed", "unsupported"):
        if fail not in _FAILURE_REASONS:
            if not has_token and out["provider"] in _CANONICAL_PROVIDERS:
                fail = "token_unavailable"
            else:
                fail = "client_error"
        out["failure_reason"] = fail
    else:
        out.pop("failure_reason", None)

    out["attestation_schema_version"] = ATTESTATION_SCHEMA_VERSION
    return out


def attestation_signal_tags(device_context: dict[str, Any] | None) -> list[str]:
    """Derive sdk:attestation_* tags from normalized device_context."""
    if not device_context:
        return []
    plat = str(device_context.get("platform") or "web").strip().lower() or "web"
    att = device_context.get("attestation")
    if not isinstance(att, dict):
        return []
    status = str(att.get("status") or "").strip().lower()
    provider = str(att.get("provider") or "").strip().lower()
    tags: list[str] = []
    if status == "obtained":
        tags.append("sdk:attestation_obtained")
        tags.append("sdk:attestation_present")
    if att.get("verified") is True:
        tags.append("sdk:attestation_verified")
    if status in ("failed", "unsupported"):
        tags.append("sdk:attestation_failed")
    if plat == "android" and provider == "play_integrity" and status == "obtained":
        tags.append("sdk:attestation_play_integrity")
    if plat == "ios" and provider == "app_attest" and status == "obtained":
        tags.append("sdk:attestation_app_attest")
    return list(dict.fromkeys(tags))
