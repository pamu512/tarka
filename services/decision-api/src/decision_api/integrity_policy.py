from __future__ import annotations

from typing import Any

"""Platform × signal integrity expectations (competitive gap: policy-driven confidence)."""
# platform -> list of (required_signal_prefix_or_tag, min_fraction_of_required_met)
# min_fraction 1.0 means all listed must be absent of tamper tags for "full" trust boost.
_INTEGRITY_EXPECTATIONS: dict[str, list[tuple[str, float]]] = {
    "web": [],
    "android": [("sdk:repackaged", 1.0), ("sdk:emulator", 1.0)],
    "ios": [("sdk:repackaged", 1.0), ("sdk:emulator", 1.0)],
    "server": [],
}

# What counts as high-confidence integrity evidence per platform (Wave 2 matrix).
_ATTESTATION_PROVIDERS: dict[str, dict[str, Any]] = {
    "web": {
        "high_confidence_signals": [
            "tls_pinning_verified",
            "replay_signature_ok",
            "captcha_passed",
        ],
        "attestation_provider": None,
        "min_integrity_confidence": 0.55,
    },
    "android": {
        "high_confidence_signals": [
            "play_integrity_verified",
            "replay_signature_ok",
            "not_emulator",
            "not_repackaged",
        ],
        "attestation_provider": "play_integrity",
        "min_integrity_confidence": 0.7,
    },
    "ios": {
        "high_confidence_signals": [
            "app_attest_verified",
            "replay_signature_ok",
            "not_repackaged",
        ],
        "attestation_provider": "app_attest",
        "min_integrity_confidence": 0.7,
    },
    "server": {
        "high_confidence_signals": ["hmac_request_ok", "replay_signature_ok"],
        "attestation_provider": None,
        "min_integrity_confidence": 0.5,
    },
}


def integrity_policy_matrix() -> dict[str, Any]:
    """Public matrix for ops / CI: platforms, tamper markers, attestation providers."""
    platforms: dict[str, Any] = {}
    for plat, rules in _INTEGRITY_EXPECTATIONS.items():
        att = _ATTESTATION_PROVIDERS.get(plat, {})
        platforms[plat] = {
            "tamper_markers_clear_required": [m for m, _ in rules],
            "attestation_provider": att.get("attestation_provider"),
            "high_confidence_signals": list(att.get("high_confidence_signals") or []),
            "min_integrity_confidence_for_auto_action": att.get(
                "min_integrity_confidence"
            ),
        }
    return {
        "schema_id": "tarka.integrity_policy_matrix/v1",
        "platforms": platforms,
        "note": (
            "High-confidence auto-actions should require min_integrity_confidence "
            "and platform attestation when attestation_provider is set."
        ),
    }


def integrity_ingress_status(
    *,
    request_signature_required: bool,
    request_signature_max_skew_seconds: int,
    integrity_soft_tags: bool,
    challenge_webhook_configured: bool,
    enforcement_webhook_configured: bool = False,
    replay_payload_ttl_seconds: int = 300,
    request_signature_path_prefixes: tuple[str, ...] = ("/v1/decisions/evaluate",),
) -> dict[str, Any]:
    """Ops-facing ingress integrity flags (signing / soft tags / act webhooks)."""
    return {
        "schema_id": "tarka.integrity_ingress/v1",
        "request_signature_required": bool(request_signature_required),
        "request_signature_max_skew_seconds": int(request_signature_max_skew_seconds),
        "request_signature_path_prefixes": list(request_signature_path_prefixes),
        "integrity_soft_tags": bool(integrity_soft_tags),
        "replay_payload_ttl_seconds": int(replay_payload_ttl_seconds),
        "challenge_webhook_configured": bool(challenge_webhook_configured),
        "enforcement_webhook_configured": bool(enforcement_webhook_configured),
        "integrity_policy_endpoint": "GET /v1/ops/integrity-policy",
        "docs": "docs/docs/guides/tls-pinning-and-signed-requests.md",
        "decide_to_act_docs": "docs/docs/guides/decide-to-act-enforcement.md",
    }


def apply_evaluate_integrity_tags(
    signal_tags: list[str],
    *,
    hmac_ok: bool | None,
    request_signature_required: bool,
    integrity_soft_tags: bool,
    tls_pinning_verified: bool | None,
    is_replayed: bool,
) -> list[str]:
    """Append ingress integrity tags for evaluate (idempotent-ish; caller owns dedupe)."""
    out: list[str] = []
    if hmac_ok is True:
        out.append("ingress:hmac_request_ok")
    elif request_signature_required and integrity_soft_tags and hmac_ok is not True:
        # Middleware normally 401s before evaluate when secret is set; soft path for tests.
        out.append("integrity:hmac_request_missing")
    elif integrity_soft_tags and not request_signature_required:
        out.append("integrity:hmac_not_configured")

    if not is_replayed:
        out.append("ingress:replay_signature_ok")

    if tls_pinning_verified is True:
        out.append("ingress:tls_pinning_verified")
    elif integrity_soft_tags and tls_pinning_verified is not True:
        out.append("integrity:tls_pinning_unverified")

    # Dedupe while preserving order against existing tags.
    have = set(signal_tags)
    return [t for t in out if t not in have]


def min_integrity_confidence_for_platform(platform: str) -> float:
    """Matrix floor for auto step-up / challenge recommendations."""
    plat = (platform or "web").strip().lower()
    att = _ATTESTATION_PROVIDERS.get(plat, _ATTESTATION_PROVIDERS["web"])
    return float(att.get("min_integrity_confidence") or 0.5)


def platform_meets_high_confidence(
    platform: str,
    *,
    integrity_confidence: float,
    verified_signals: list[str] | None = None,
) -> bool:
    """True when confidence and optional verified signal names meet the matrix bar."""
    plat = (platform or "web").strip().lower()
    att = _ATTESTATION_PROVIDERS.get(plat, _ATTESTATION_PROVIDERS["web"])
    min_c = min_integrity_confidence_for_platform(plat)
    if integrity_confidence < min_c:
        return False
    required = list(att.get("high_confidence_signals") or [])
    if not required:
        return True
    have = {s.strip().lower() for s in (verified_signals or []) if s}
    # At least one named high-confidence signal when attestation is configured.
    if att.get("attestation_provider"):
        return any(r.lower() in have for r in required)
    return True


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


def parse_session_geo(
    features: dict[str, Any],
) -> tuple[float | None, float | None, float | None]:
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
