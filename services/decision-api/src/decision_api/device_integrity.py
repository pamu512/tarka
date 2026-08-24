"""Native device-integrity slice for evaluate snapshots (no attestation verify)."""

from __future__ import annotations

from typing import Any, Literal

# Booleans the desk pins on the open case. Tags are added only when these are True.
INTEGRITY_SIGNAL_KEYS = ("is_rooted", "is_jailbroken", "has_biometrics")

IntegrityPresence = Literal["true", "present", "missing"]


def integrity_presence(signals: dict[str, Any] | None) -> dict[str, IntegrityPresence]:
    """Present vs missing vs true — never invent false for omitted integrity keys.

    ``true``: SDK sent the boolean True.
    ``present``: SDK sent the boolean False (field was bound; not clean-by-omission).
    ``missing``: key omitted or not a bool.
    """
    src = signals if isinstance(signals, dict) else {}
    out: dict[str, IntegrityPresence] = {}
    for key in INTEGRITY_SIGNAL_KEYS:
        if key not in src or not isinstance(src[key], bool):
            out[key] = "missing"
        elif src[key] is True:
            out[key] = "true"
        else:
            out[key] = "present"
    return out


def audit_integrity(snap: dict[str, Any] | None) -> dict[str, IntegrityPresence]:
    """Integrity map for decision-row / FLAG projections. Always all three keys."""
    out = integrity_presence(None)
    if not isinstance(snap, dict):
        return out
    raw = snap.get("integrity")
    if isinstance(raw, dict):
        for key in INTEGRITY_SIGNAL_KEYS:
            val = raw.get(key)
            if val in ("true", "present", "missing"):
                out[key] = val  # type: ignore[assignment]
        return out
    dc = snap.get("device_context")
    signals = dc.get("signals") if isinstance(dc, dict) else None
    return integrity_presence(signals if isinstance(signals, dict) else None)


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
    presence = integrity_presence(signals_in if isinstance(signals_in, dict) else None)
    if not signals and not platform:
        return None
    out: dict[str, Any] = {"signals": signals, "integrity": presence}
    if platform:
        out["platform"] = platform
    return out
