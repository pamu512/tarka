"""Native device-integrity slice for evaluate snapshots (no attestation verify)."""

from __future__ import annotations

from typing import Any

# Booleans the desk pins on the open case. Tags are added only when these are True.
INTEGRITY_SIGNAL_KEYS = ("is_rooted", "is_jailbroken", "has_biometrics")


def device_integrity_snapshot(
    device_context: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Slim device_context for the investigator path: platform + integrity booleans only.

    Omits device_id and attestation tokens. Absent booleans stay absent (never invented false).
    """
    if not isinstance(device_context, dict):
        return None
    signals_in = device_context.get("signals")
    signals: dict[str, bool] = {}
    if isinstance(signals_in, dict):
        for key in INTEGRITY_SIGNAL_KEYS:
            val = signals_in.get(key)
            if isinstance(val, bool):
                signals[key] = val
    platform = str(device_context.get("platform") or "").strip()
    if not signals and not platform:
        return None
    out: dict[str, Any] = {"signals": signals}
    if platform:
        out["platform"] = platform
    return out
