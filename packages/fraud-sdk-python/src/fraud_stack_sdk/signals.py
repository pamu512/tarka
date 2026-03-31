"""Server-side signal collector for Python SDK."""
from __future__ import annotations

import hashlib
import ipaddress
import os
from typing import Any

# Known datacenter/proxy ASN prefixes (lightweight list; extend or use MaxMind)
_DATACENTER_ASNS = frozenset({
    "AS14061",  # DigitalOcean
    "AS16509",  # Amazon AWS
    "AS15169",  # Google Cloud
    "AS13335",  # Cloudflare
    "AS8075",   # Microsoft Azure
    "AS20473",  # Vultr
    "AS63949",  # Linode
})

_PROXY_HEADERS = (
    "x-forwarded-for",
    "via",
    "x-real-ip",
    "forwarded",
)


def _is_private_ip(ip: str) -> bool:
    try:
        return ipaddress.ip_address(ip).is_private
    except ValueError:
        return False


class ServerSignalCollector:
    """Extracts server-side signals from an incoming HTTP request context.

    Usage::

        collector = ServerSignalCollector()
        signals = collector.collect(
            ip="203.0.113.5",
            headers={"x-forwarded-for": "1.2.3.4, 5.6.7.8", "user-agent": "..."},
        )
    """

    def __init__(self, geo_lookup_url: str = "") -> None:
        self._geo_url = geo_lookup_url or os.environ.get("GEO_LOOKUP_URL", "")

    def collect(
        self,
        ip: str,
        headers: dict[str, str] | None = None,
        asn: str | None = None,
        country: str | None = None,
    ) -> dict[str, Any]:
        headers = {k.lower(): v for k, v in (headers or {}).items()}
        forwarded = headers.get("x-forwarded-for", "")
        has_proxy_headers = any(h in headers for h in _PROXY_HEADERS if headers.get(h))

        is_datacenter = (asn or "").upper() in _DATACENTER_ASNS
        is_proxy = has_proxy_headers and not _is_private_ip(ip)
        ua = headers.get("user-agent", "")
        bot_ua = any(kw in ua.lower() for kw in ("bot", "crawler", "spider", "curl", "wget", "python-requests"))

        return {
            "ip_address": ip,
            "ip_forwarded_for": forwarded or None,
            "ip_geo_country": country,
            "ip_asn": asn,
            "ip_is_proxy": is_proxy,
            "ip_is_datacenter": is_datacenter,
            "is_bot": bot_ua,
            "user_agent": ua or None,
        }

    def build_device_context(
        self,
        ip: str,
        headers: dict[str, str] | None = None,
        asn: str | None = None,
        country: str | None = None,
        client_device_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        server_signals = self.collect(ip=ip, headers=headers, asn=asn, country=country)

        if client_device_context:
            merged_signals = {**client_device_context.get("signals", {}), **server_signals}
            return {
                **client_device_context,
                "signals": merged_signals,
            }

        device_id = hashlib.sha256(f"{ip}|{headers.get('user-agent', '') if headers else ''}".encode()).hexdigest()
        return {
            "device_id": device_id,
            "platform": "server",
            "signals": server_signals,
            "attestation": None,
        }
