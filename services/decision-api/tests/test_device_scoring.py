"""device_scoring telemetry decode + anomaly tags."""

from __future__ import annotations

import hashlib
import json

from decision_api.device_scoring import (
    decode_telemetry_packet,
    extract_device_entropy_tags,
)


def _seal(payload: dict) -> dict:
    raw = json.dumps(payload, separators=(",", ":"))
    enc = (
        __import__("base64")
        .urlsafe_b64encode(raw.encode("utf-8"))
        .decode("ascii")
        .rstrip("=")
    )
    digest = hashlib.sha256(enc.encode("utf-8")).hexdigest()
    return {"v": 1, "enc": enc, "int": digest}


def test_decode_telemetry_packet_round_trip() -> None:
    inner = {"mouse": {"path_jitter_px": 1.2}, "typing": {"key_count": 3}}
    behavior = {"telemetry_packet": _seal(inner)}
    out = decode_telemetry_packet(behavior)
    assert out == inner


def test_decode_telemetry_packet_tamper() -> None:
    inner = {"a": 1}
    pkt = _seal(inner)
    pkt["int"] = "0" * 64
    out = decode_telemetry_packet({"telemetry_packet": pkt})
    assert out == {"_tampered": True}


def test_extract_zero_mouse_jitter_tag() -> None:
    dc = {
        "signals": {},
        "behavior": {
            "mouse": {
                "path_jitter_px": 0,
                "samples_per_second_est": 0.2,
                "path_length_px": 0,
                "click_count": 4,
            },
            "typing": {
                "key_count": 5,
                "std_inter_key_ms": 20,
                "hesitation_events_gt_500ms": 1,
            },
            "touch": {},
        },
    }
    tags = extract_device_entropy_tags(dc)
    assert "device:zero_mouse_jitter" in tags


def test_extract_webrtc_private_tag() -> None:
    dc = {
        "signals": {"entropy_webrtc_private_candidate": True},
        "behavior": {"mouse": {}, "typing": {}, "touch": {}},
    }
    assert "device:webrtc_private_candidate" in extract_device_entropy_tags(dc)
