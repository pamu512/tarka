from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from decision_api.integrity_policy import haversine_km

"""Derive session geo + consistency hints from device signals and IP/OSINT features."""
_GEO_SOURCES_TRUST_GPS = frozenset({"browser_gps", "android_gps", "ios_gps"})


def _parse_iso_ts(raw: Any) -> float | None:
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        return float(raw)
    s = str(raw).strip()
    if not s:
        return None
    try:
        if s.isdigit():
            v = int(s)
            if v >= 1_000_000_000_000:  # milliseconds (13+ digits)
                return v / 1000.0
            return float(v)
    except (TypeError, ValueError):
        pass
    try:
        s2 = s.replace("Z", "+00:00")
        dt = datetime.fromisoformat(s2)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.timestamp()
    except (ValueError, TypeError):
        return None


def _tz_region_hint(tz_name: str | None) -> str | None:
    if not tz_name or not isinstance(tz_name, str):
        return None
    m = re.search(r"/([^/]+)$", tz_name.strip())
    if not m:
        return None
    return m.group(1).replace("_", " ").lower()


def merge_session_geo_from_device_and_features(features: dict[str, Any]) -> list[str]:
    """Fill session_last_* from SDK/IP when absent; return extra signal tags (geo consistency)."""
    tags: list[str] = []
    # features dict may be flat merge from device_context.signals — keys at top level
    geo_lat = features.get("geo_lat")
    geo_lon = features.get("geo_lon")
    geo_src = features.get("geo_source")
    geo_ts = features.get("geo_ts")
    acc = features.get("geo_accuracy_m")

    ip_la = features.get("ip_geo_lat")
    ip_lo = features.get("ip_geo_lon")
    ip_tz = features.get("ip_geo_timezone")
    dev_tz = features.get("timezone")

    try:
        gla = float(geo_lat) if geo_lat is not None else None
        glo = float(geo_lon) if geo_lon is not None else None
    except (TypeError, ValueError):
        gla, glo = None, None
    try:
        ipla = float(ip_la) if ip_la is not None else None
        iplo = float(ip_lo) if ip_lo is not None else None
    except (TypeError, ValueError):
        ipla, iplo = None, None

    ts_parsed = _parse_iso_ts(geo_ts)
    if ts_parsed is None and gla is not None and glo is not None:
        ts_parsed = datetime.now(timezone.utc).timestamp()

    src_s = str(geo_src).strip().lower() if geo_src is not None else ""
    if gla is not None and glo is not None and -90 <= gla <= 90 and -180 <= glo <= 180:
        features.setdefault("session_last_lat", gla)
        features.setdefault("session_last_lon", glo)
        if ts_parsed is not None:
            features.setdefault("session_last_ts", ts_parsed)
        if acc is not None:
            try:
                features.setdefault("geo_accuracy_m", float(acc))
            except (TypeError, ValueError):
                pass
        if src_s:
            features.setdefault("geo_source_resolved", src_s)
    elif ipla is not None and iplo is not None:
        features.setdefault("session_last_lat", ipla)
        features.setdefault("session_last_lon", iplo)
        features.setdefault("session_last_ts", datetime.now(timezone.utc).timestamp())
        features.setdefault("geo_source_resolved", "ip_geolocation")

    # Device vs IP distance (OSS / provider-agnostic)
    if (
        gla is not None
        and glo is not None
        and ipla is not None
        and iplo is not None
        and src_s in _GEO_SOURCES_TRUST_GPS
    ):
        d_km = haversine_km(gla, glo, ipla, iplo)
        features["geo_device_ip_delta_km"] = round(d_km, 2)
        if d_km > 500.0:
            tags.append("sdk:geo_ip_mismatch")

    # Optional: coarse timezone label vs IANA timezone (weak signal)
    if isinstance(dev_tz, str) and dev_tz and isinstance(ip_tz, str) and ip_tz:
        hint = _tz_region_hint(dev_tz)
        ip_part = (
            ip_tz.split("/")[-1].replace("_", " ").lower()
            if "/" in ip_tz
            else ip_tz.lower()
        )
        if hint and ip_part and hint not in ip_part and ip_part not in hint:
            tags.append("sdk:geo_tz_mismatch")

    return tags
