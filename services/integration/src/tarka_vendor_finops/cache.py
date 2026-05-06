"""Redis-backed vendor signal cache with per-signal TTL and negative caching."""

from __future__ import annotations

import hashlib
import json
import logging
from enum import StrEnum
from typing import Any

from redis.asyncio import Redis

log = logging.getLogger(__name__)


class SignalKind(StrEnum):
    IP = "ip"
    EMAIL = "email"
    PHONE = "phone"
    DOMAIN = "domain"
    IDENTITY = "identity"


# Default TTLs (seconds): IP rotates faster; email identity slower.
DEFAULT_TTLS: dict[SignalKind, int] = {
    SignalKind.IP: 86_400,  # 24h
    SignalKind.EMAIL: 604_800,  # 7d
    SignalKind.PHONE: 86_400,
    SignalKind.DOMAIN: 604_800,
    SignalKind.IDENTITY: 604_800,
}

# Map OSINT vendor_key (integration_ingress.osint) → signal kind for TTL selection.
VENDOR_SIGNAL_KIND: dict[str, SignalKind] = {
    "shodan": SignalKind.IP,
    "abuseipdb": SignalKind.IP,
    "greynoise": SignalKind.IP,
    "ipinfo": SignalKind.IP,
    "ip_api": SignalKind.IP,
    "emailrep": SignalKind.EMAIL,
    "gravatar": SignalKind.EMAIL,
    "hibp": SignalKind.EMAIL,
    "numverify": SignalKind.PHONE,
    "rdap": SignalKind.DOMAIN,
    "github": SignalKind.IDENTITY,
}


def cache_ttl_for_vendor(
    vendor_key: str,
    *,
    ttl_overrides: dict[str, int] | None = None,
    default_ttls: dict[SignalKind, int] | None = None,
) -> int:
    kind = VENDOR_SIGNAL_KIND.get(vendor_key, SignalKind.IP)
    base = (default_ttls or DEFAULT_TTLS).get(kind, DEFAULT_TTLS[SignalKind.IP])
    if ttl_overrides and vendor_key in ttl_overrides:
        return int(ttl_overrides[vendor_key])
    return int(base)


def _cache_key(tenant_id: str, vendor_key: str, url: str) -> str:
    tid = (tenant_id or "global").strip() or "global"
    fp = hashlib.sha256(f"{vendor_key}\n{url}".encode()).hexdigest()[:40]
    return f"vendorsig:{tid}:{vendor_key}:{fp}"


class VendorSignalCache:
    """Stores successful JSON payloads and negative outcomes (404 / transport errors)."""

    def __init__(self, redis: Redis) -> None:
        self._r = redis

    async def get_json(self, tenant_id: str, vendor_key: str, url: str) -> dict[str, Any] | None:
        raw = await self._r.get(_cache_key(tenant_id, vendor_key, url))
        if not raw:
            return None
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            log.warning("vendor_signal_cache corrupt json for %s", vendor_key)
            return None

    async def set_positive(
        self,
        tenant_id: str,
        vendor_key: str,
        url: str,
        payload: dict[str, Any],
        *,
        ttl_seconds: int,
    ) -> None:
        body = {"__meta__": {"negative": False}, "payload": payload}
        await self._r.set(
            _cache_key(tenant_id, vendor_key, url),
            json.dumps(body, default=str, separators=(",", ":")),
            ex=max(60, int(ttl_seconds)),
        )

    async def set_negative(
        self,
        tenant_id: str,
        vendor_key: str,
        url: str,
        *,
        status_code: int | None,
        error_class: str,
        message: str,
        ttl_seconds: int,
    ) -> None:
        """Cache absence of useful data so we do not hammer failing endpoints."""
        body = {
            "__meta__": {
                "negative": True,
                "status_code": status_code,
                "error_class": error_class,
                "message": (message or "")[:512],
            },
            "payload": None,
        }
        await self._r.set(
            _cache_key(tenant_id, vendor_key, url),
            json.dumps(body, default=str, separators=(",", ":")),
            ex=max(60, int(ttl_seconds)),
        )

    @staticmethod
    def unwrap_entry(entry: dict[str, Any]) -> tuple[bool, dict[str, Any] | None]:
        """Return (is_negative, payload_or_none)."""
        meta = entry.get("__meta__") if isinstance(entry.get("__meta__"), dict) else {}
        if meta.get("negative"):
            return True, None
        p = entry.get("payload")
        if isinstance(p, dict):
            return False, p
        return False, None
