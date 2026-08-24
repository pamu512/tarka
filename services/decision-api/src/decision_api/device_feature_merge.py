"""Merge evaluate device_context into the features dict for JSON rules."""

from __future__ import annotations

from typing import Any

from decision_api.device_integrity import INTEGRITY_SIGNAL_KEYS
from decision_api.schemas import DeviceContextIn


def merge_device_context_into_features(
    features: dict[str, Any],
    device_context: DeviceContextIn | None,
) -> None:
    """Expose SDK signals and a stable ``device_fingerprint`` string for rules.

    Integrity keys (rooted / jailbroken / biometrics) are copied only when they
    are real booleans. Omitted keys stay absent — never invented ``False``.
    """
    if device_context is None:
        return
    for key, value in device_context.signals.items():
        if key in INTEGRITY_SIGNAL_KEYS and not isinstance(value, bool):
            continue
        features.setdefault(key, value)
    features.setdefault("device_fingerprint", device_context.device_id)
