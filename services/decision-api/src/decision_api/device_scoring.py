"""Parse browser SDK telemetry + flag device entropy anomalies (behavioral biometrics, evasion)."""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import math
from typing import Any

_TELEMETRY_PACKET_VERSION = 1


def _b64url_decode(s: str) -> bytes:
    pad = "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode((s + pad).encode("ascii"))


def decode_telemetry_packet(behavior: dict[str, Any] | None) -> dict[str, Any] | None:
    """Decode ``behavior.telemetry_packet`` (base64url JSON + SHA-256 integrity). Returns None if missing/invalid."""
    if not behavior or not isinstance(behavior, dict):
        return None
    raw = behavior.get("telemetry_packet")
    if not isinstance(raw, dict):
        return None
    if int(raw.get("v") or 0) != _TELEMETRY_PACKET_VERSION:
        return None
    enc = raw.get("enc")
    digest = raw.get("int")
    if not isinstance(enc, str) or not isinstance(digest, str):
        return None
    try:
        body = _b64url_decode(enc).decode("utf-8")
    except (UnicodeDecodeError, binascii.Error, ValueError):
        return None
    expect = hashlib.sha256(enc.encode("utf-8")).hexdigest()
    if expect != digest:
        return {"_tampered": True}
    try:
        return json.loads(body)
    except json.JSONDecodeError:
        return None


def extract_device_entropy_tags(device_context: dict[str, Any] | None) -> list[str]:
    """Derive ``device:*`` tags from ``device_context.signals`` + sealed telemetry + live ``behavior``."""
    if not device_context:
        return []
    tags: list[str] = []
    signals = device_context.get("signals") or {}
    behavior = device_context.get("behavior") or {}

    mouse = behavior.get("mouse") or {}
    typing = behavior.get("typing") or {}
    touch = behavior.get("touch") or {}

    jitter = _safe_float(mouse.get("path_jitter_px"))
    sps = _safe_float(mouse.get("samples_per_second_est"))
    path_len = _safe_float(mouse.get("path_length_px"))
    clicks = int(mouse.get("click_count") or 0)

    if clicks >= 2 and jitter == 0.0 and sps < 1.0 and path_len < 1.0:
        tags.append("device:zero_mouse_jitter")

    std_typing = _safe_float(typing.get("std_inter_key_ms"))
    keys = int(typing.get("key_count") or 0)
    if keys > 25 and std_typing < 4.0:
        tags.append("device:flat_typing_entropy")

    hes = int(typing.get("hesitation_events_gt_500ms") or 0)
    if keys > 40 and hes == 0 and std_typing < 8.0:
        tags.append("device:no_typing_hesitation")

    if signals.get("entropy_webrtc_private_candidate") is True:
        tags.append("device:webrtc_private_candidate")

    if signals.get("headless_detected") is True and not signals.get("entropy_canvas_raster_digest"):
        tags.append("device:canvas_entropy_missing_headless")

    hw = signals.get("entropy_hardware_concurrency")
    if isinstance(hw, int) and hw == 1:
        tags.append("device:hardware_concurrency_suspicious")

    decoded = decode_telemetry_packet(behavior if isinstance(behavior, dict) else None)
    if decoded is None and isinstance(behavior, dict) and behavior.get("telemetry_packet"):
        tags.append("device:telemetry_packet_invalid")
    elif isinstance(decoded, dict) and decoded.get("_tampered"):
        tags.append("device:telemetry_packet_tampered")

    return list(dict.fromkeys(tags))


def _safe_float(v: Any) -> float:
    try:
        x = float(v)
        return x if math.isfinite(x) else 0.0
    except (TypeError, ValueError):
        return 0.0
