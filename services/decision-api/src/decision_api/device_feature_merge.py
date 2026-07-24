"""Merge evaluate device_context into the features dict for JSON rules."""

from __future__ import annotations

from typing import Any

from decision_api.schemas import DeviceContextIn


def merge_device_context_into_features(
    features: dict[str, Any],
    device_context: DeviceContextIn | None,
) -> None:
    """Expose SDK signals and a stable ``device_fingerprint`` string for rules."""
    if device_context is None:
        return
    for key, value in device_context.signals.items():
        features.setdefault(key, value)
    features.setdefault("device_fingerprint", device_context.device_id)
