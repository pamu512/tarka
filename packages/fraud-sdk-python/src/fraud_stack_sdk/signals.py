from __future__ import annotations

import hashlib
import ipaddress
import json
import os
import urllib.error
import urllib.request
from typing import Any

"""Server-side signal collector for Python SDK."""
# Known datacenter/proxy ASN prefixes (lightweight list; extend or use MaxMind)
_DATACENTER_ASNS = frozenset(
    {
        "AS14061",  # DigitalOcean
        "AS16509",  # Amazon AWS
        "AS15169",  # Google Cloud
        "AS13335",  # Cloudflare
        "AS8075",  # Microsoft Azure
        "AS20473",  # Vultr
        "AS63949",  # Linode
    }
)

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


def _lookup_ip_geo_public(ip: str) -> tuple[float | None, float | None, str | None]:
    """Best-effort IP geolocation via ip-api.com (no key; rate-limited). Skips private IPs."""
    if _is_private_ip(ip):
        return None, None, None
    try:
        req = urllib.request.Request(
            f"http://ip-api.com/json/{ip}?fields=status,lat,lon,timezone",
            headers={"User-Agent": "tarka-fraud-sdk-python"},
        )
        with urllib.request.urlopen(req, timeout=2.0) as resp:
            raw = resp.read().decode()
        data = json.loads(raw)
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, ValueError):
        return None, None, None
    if not isinstance(data, dict) or data.get("status") != "success":
        return None, None, None
    la = data.get("lat")
    lo = data.get("lon")
    tz = data.get("timezone")
    try:
        gla = float(la) if la is not None else None
        glo = float(lo) if lo is not None else None
    except (TypeError, ValueError):
        return None, None, None
    tz_s = str(tz).strip() if isinstance(tz, str) and tz.strip() else None
    return gla, glo, tz_s


class ServerSignalCollector:
    """Extracts server-side signals from an incoming HTTP request context.

    Usage::

        collector = ServerSignalCollector()
        signals = collector.collect(
            ip="203.0.113.5",
            headers={"x-forwarded-for": "1.2.3.4, 5.6.7.8", "user-agent": "..."},
        )
    """

    def __init__(self, geo_lookup_url: str = "", *, enable_ip_geo: bool | None = None) -> None:
        self._geo_url = geo_lookup_url or os.environ.get("GEO_LOOKUP_URL", "")
        env_flag = os.environ.get("ENABLE_IP_GEO_LOOKUP", "").strip().lower()
        env_enabled = env_flag in {"1", "true", "yes", "on"}
        self._enable_ip_geo = bool(enable_ip_geo) if enable_ip_geo is not None else env_enabled

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
        bot_ua = any(
            kw in ua.lower()
            for kw in ("bot", "crawler", "spider", "curl", "wget", "python-requests")
        )

        out: dict[str, Any] = {
            "ip_address": ip,
            "ip_forwarded_for": forwarded or None,
            "ip_geo_country": country,
            "ip_asn": asn,
            "ip_is_proxy": is_proxy,
            "ip_is_datacenter": is_datacenter,
            "is_bot": bot_ua,
            "user_agent": ua or None,
        }
        if self._enable_ip_geo:
            gla, glo, gtz = _lookup_ip_geo_public(ip)
            if gla is not None:
                out["ip_geo_lat"] = gla
            if glo is not None:
                out["ip_geo_lon"] = glo
            if gtz:
                out["ip_geo_timezone"] = gtz
        return out

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

        device_id = hashlib.sha256(
            f"{ip}|{headers.get('user-agent', '') if headers else ''}".encode()
        ).hexdigest()
        return {
            "device_id": device_id,
            "platform": "server",
            "signals": server_signals,
            "attestation": None,
        }
