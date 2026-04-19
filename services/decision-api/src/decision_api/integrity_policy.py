"""Platform × signal integrity expectations (competitive gap: policy-driven confidence)."""

from __future__ import annotations

from typing import Any

# platform -> list of (required_signal_prefix_or_tag, min_fraction_of_required_met)
# min_fraction 1.0 means all listed must be absent of tamper tags for "full" trust boost.
_INTEGRITY_EXPECTATIONS: dict[str, list[tuple[str, float]]] = {
    "web": [],
    "android": [("sdk:repackaged", 1.0), ("sdk:emulator", 1.0)],
    "ios": [("sdk:repackaged", 1.0), ("sdk:emulator", 1.0)],
    "server": [],
}


def supplemental_tags_for_integrity(platform: str, signal_tags: list[str]) -> list[str]:
    """Emit integrity:* tags when platform expectations are violated."""
    plat = (platform or "web").strip().lower()
    tags = set(signal_tags)
    out: list[str] = []
    rules = _INTEGRITY_EXPECTATIONS.get(plat, _INTEGRITY_EXPECTATIONS["web"])
    for marker, need_clear in rules:
        if not marker:
            continue
        if marker.endswith(":"):
            hits = sum(1 for t in tags if t.startswith(marker))
            if hits and need_clear >= 1.0:
                out.append(f"integrity:{plat}_signal_anomaly")
        elif marker in tags and need_clear >= 1.0:
            out.append(f"integrity:{marker.replace(':', '_')}_present")
    return out


def adjust_integrity_confidence(
    base: float,
    platform: str,
    signal_tags: list[str],
    *,
    pinning_ok: bool | None = None,
) -> float:
    """Optional TLS pinning hint from client metadata lowers MitM concern."""
    conf = max(0.0, min(1.0, base))
    if pinning_ok is True:
        conf = min(1.0, conf + 0.05)
    elif pinning_ok is False:
        conf = max(0.0, conf - 0.08)
    supplemental = supplemental_tags_for_integrity(platform, signal_tags)
    if supplemental:
        conf = max(0.0, conf - 0.04 * min(len(supplemental), 3))
    return round(conf, 4)


def parse_session_geo(features: dict[str, Any]) -> tuple[float | None, float | None, float | None]:
    """session_last_lat, session_last_lon, session_last_ts from evaluate payload/features."""
    lat = features.get("session_last_lat")
    lon = features.get("session_last_lon")
    ts = features.get("session_last_ts")
    try:
        la = float(lat) if lat is not None else None
    except (TypeError, ValueError):
        la = None
    try:
        lo = float(lon) if lon is not None else None
    except (TypeError, ValueError):
        lo = None
    try:
        t = float(ts) if ts is not None else None
    except (TypeError, ValueError):
        t = None
    return la, lo, t


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in km."""
    from math import asin, cos, radians, sin, sqrt

    r = 6371.0
    p1, p2 = radians(lat1), radians(lat2)
    dphi = radians(lat2 - lat1)
    dl = radians(lon2 - lon1)
    h = sin(dphi / 2) ** 2 + cos(p1) * cos(p2) * sin(dl / 2) ** 2
    return 2 * r * asin(sqrt(min(1.0, h)))


def trusted_zone_hit(
    lat: float | None,
    lon: float | None,
    zones: list[dict[str, Any]] | None,
) -> bool:
    if lat is None or lon is None or not zones:
        return False
    for z in zones:
        try:
            zlat = float(z.get("lat"))
            zlon = float(z.get("lon"))
            rad = float(z.get("radius_km", 50))
        except (TypeError, ValueError):
            continue
        if haversine_km(lat, lon, zlat, zlon) <= rad:
            return True
    return False
