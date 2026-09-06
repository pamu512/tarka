"""Merge evaluate device_context into the features dict for JSON rules."""

from __future__ import annotations

from typing import Any

from decision_api.device_integrity import INTEGRITY_SIGNAL_KEYS
from decision_api.schemas import DeviceContextIn

# Keep aligned with decision_api.main._SIGNAL_TAG_MAP keys.
_SIGNAL_BOOL_KEYS = frozenset(INTEGRITY_SIGNAL_KEYS) | frozenset(
    {
        "is_emulator",
        "is_vpn",
        "is_bot",
        "is_repackaged",
        "is_spoofed_location",
        "webdriver_detected",
        "headless_detected",
        "automation_detected",
        "timezone_geo_mismatch",
        "vpn_interface_detected",
        "mock_location_detected",
        "geo_ip_mismatch",
        "geo_tz_mismatch",
        "ip_is_proxy",
        "ip_is_datacenter",
    }
)


def merge_device_context_into_features(
    features: dict[str, Any],
    device_context: DeviceContextIn | None,
) -> None:
    """Expose SDK signals and a stable ``device_fingerprint`` string for rules.

    SDK bool keys are copied only when they are real booleans. Omitted keys
    stay absent — never invented ``False``.
    """
    if device_context is None:
        return
    for key, value in device_context.signals.items():
        if key in _SIGNAL_BOOL_KEYS and not isinstance(value, bool):
            continue
        features.setdefault(key, value)
    features.setdefault("device_fingerprint", device_context.device_id)
