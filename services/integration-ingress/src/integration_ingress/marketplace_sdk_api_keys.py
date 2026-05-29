"""Marketplace SDK API keys — issue, list, revoke (Prompt 174)."""

from __future__ import annotations

import hashlib
import json
import logging
import secrets
import uuid
from datetime import UTC, datetime
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

SdkPlatform = Literal["sdk-python", "sdk-typescript", "sdk-android", "sdk-ios", "sdk-web"]

SDK_PLATFORMS: tuple[dict[str, Any], ...] = (
    {
        "id": "sdk-python",
        "name": "Python SDK",
        "codename": "Duta",
        "description": "Server-side evaluate + ingest",
        "default_scopes": ["evaluate", "ingest"],
        "env_var": "TARKA_API_KEY",
    },
    {
        "id": "sdk-typescript",
        "name": "TypeScript SDK",
        "codename": "Darpana",
        "description": "Browser behavioral biometrics + attestation",
        "default_scopes": ["evaluate", "ingest", "attestation"],
        "env_var": "TARKA_API_KEY",
    },
    {
        "id": "sdk-android",
        "name": "Android SDK",
        "codename": "Kavacha",
        "description": "Play Integrity + device signals",
        "default_scopes": ["evaluate", "ingest", "attestation"],
        "env_var": "TARKA_API_KEY",
    },
    {
        "id": "sdk-ios",
        "name": "iOS SDK",
        "codename": "Mudra",
        "description": "App Attest + device signals",
        "default_scopes": ["evaluate", "ingest", "attestation"],
        "env_var": "TARKA_API_KEY",
    },
    {
        "id": "sdk-web",
        "name": "Web SDK",
        "codename": "Anumana",
        "description": "Marketplace web telemetry + ingest",
        "default_scopes": ["evaluate", "ingest", "marketplace_profile"],
        "env_var": "TARKA_API_KEY",
    },
)

ALLOWED_SCOPES = frozenset(
    {"evaluate", "ingest", "attestation", "marketplace_profile", "shadow_read"},
)

_KEY_PREFIX = "tarka_mkt_"


def _hash_secret(secret: str) -> str:
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


def _display_prefix(secret: str) -> str:
    tail = secret.removeprefix(_KEY_PREFIX)
    if len(tail) >= 8:
        return f"{_KEY_PREFIX}{tail[:4]}…{tail[-4:]}"
    return f"{_KEY_PREFIX}…"


def generate_sdk_api_secret() -> str:
    return f"{_KEY_PREFIX}{secrets.token_urlsafe(24)}"


def _row_to_dict(row: Any) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "tenant_id": row.tenant_id,
        "platform": row.platform,
        "label": row.label,
        "key_prefix": row.key_prefix,
        "scopes": list(row.scopes or []),
        "status": row.status,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "last_used_at": row.last_used_at.isoformat() if row.last_used_at else None,
        "created_by": row.created_by,
        "rate_limit": {
            "enabled": bool(getattr(row, "rate_limit_enabled", True)),
            "requests_per_minute": int(getattr(row, "rate_limit_rpm", None) or 600),
            "burst": int(getattr(row, "rate_limit_burst", None) or 50),
        },
    }


def validate_platform(platform: str) -> str:
    pid = (platform or "").strip()
    if not any(p["id"] == pid for p in SDK_PLATFORMS):
        raise ValueError(f"unknown platform {platform!r}")
    return pid


def normalize_scopes(scopes: list[str] | None, platform: str) -> list[str]:
    if not scopes:
        default = next((p["default_scopes"] for p in SDK_PLATFORMS if p["id"] == platform), [])
        return list(default)
    out: list[str] = []
    for s in scopes:
        sk = str(s).strip().lower()
        if sk and sk in ALLOWED_SCOPES and sk not in out:
            out.append(sk)
    if not out:
        raise ValueError("at least one valid scope required")
    return out


async def list_sdk_api_keys(session: AsyncSession, *, tenant_id: str) -> list[dict[str, Any]]:
    from integration_ingress.models import MarketplaceSdkApiKey

    tid = (tenant_id or "demo").strip() or "demo"
    rows = (
        await session.scalars(
            select(MarketplaceSdkApiKey)
            .where(MarketplaceSdkApiKey.tenant_id == tid)
            .order_by(MarketplaceSdkApiKey.created_at.desc()),
        )
    ).all()
    return [_row_to_dict(r) for r in rows]


async def create_sdk_api_key(
    session: AsyncSession,
    *,
    tenant_id: str,
    platform: str,
    label: str,
    scopes: list[str] | None,
    created_by: str | None,
) -> tuple[dict[str, Any], str]:
    from integration_ingress.models import MarketplaceSdkApiKey

    tid = (tenant_id or "demo").strip() or "demo"
    plat = validate_platform(platform)
    scope_list = normalize_scopes(scopes, plat)
    secret = generate_sdk_api_secret()
    row = MarketplaceSdkApiKey(
        id=uuid.uuid4(),
        tenant_id=tid,
        platform=plat,
        label=(label or f"{plat} key").strip()[:128],
        key_prefix=_display_prefix(secret),
        secret_hash=_hash_secret(secret),
        scopes=scope_list,
        status="active",
        created_by=(created_by or "")[:128] or None,
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return _row_to_dict(row), secret


async def revoke_sdk_api_key(
    session: AsyncSession,
    *,
    tenant_id: str,
    key_id: str,
) -> dict[str, Any] | None:
    from integration_ingress.models import MarketplaceSdkApiKey

    tid = (tenant_id or "demo").strip() or "demo"
    try:
        kid = uuid.UUID(str(key_id))
    except ValueError:
        return None
    row = await session.scalar(
        select(MarketplaceSdkApiKey).where(
            MarketplaceSdkApiKey.id == kid,
            MarketplaceSdkApiKey.tenant_id == tid,
        ),
    )
    if row is None:
        return None
    row.status = "revoked"
    row.revoked_at = datetime.now(UTC)
    await session.commit()
    await session.refresh(row)
    return _row_to_dict(row)


async def verify_sdk_api_key(
    session: AsyncSession,
    *,
    secret: str,
    required_scope: str | None = None,
) -> dict[str, Any] | None:
    """Validate ``X-API-Key`` for marketplace SDK traffic (optional scope gate)."""
    from integration_ingress.models import MarketplaceSdkApiKey

    raw = (secret or "").strip()
    if not raw.startswith(_KEY_PREFIX):
        return None
    digest = _hash_secret(raw)
    row = await session.scalar(
        select(MarketplaceSdkApiKey).where(
            MarketplaceSdkApiKey.secret_hash == digest,
            MarketplaceSdkApiKey.status == "active",
        ),
    )
    if row is None:
        return None
    from integration_ingress.marketplace_rate_limit_shields import consume_for_verified_key

    decision = consume_for_verified_key(
        str(row.id),
        enabled=bool(getattr(row, "rate_limit_enabled", True)),
        rpm=int(getattr(row, "rate_limit_rpm", None) or 600),
        burst=int(getattr(row, "rate_limit_burst", None) or 50),
    )
    if not decision.allowed:
        logger.warning("SDK API key %s rate limited (rpm=%s)", row.key_prefix, decision.limit_rpm)
        return None
    if required_scope:
        req = required_scope.strip().lower()
        scopes = {str(s).lower() for s in (row.scopes or [])}
        if req not in scopes:
            return None
    row.last_used_at = datetime.now(UTC)
    await session.commit()
    return _row_to_dict(row)


def catalog_payload() -> dict[str, Any]:
    return {"platforms": list(SDK_PLATFORMS), "allowed_scopes": sorted(ALLOWED_SCOPES)}
