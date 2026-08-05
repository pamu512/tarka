"""Production shadow evaluate: metadata.shadow=true is non-mutating for side effects."""

from __future__ import annotations

from typing import Any


def is_shadow_evaluate_request(metadata: Any) -> bool:
    """True when caller marks traffic as shadow (duplicate ingress / champion-challenger)."""
    if not isinstance(metadata, dict):
        return False
    raw = metadata.get("shadow")
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, (int, float)):
        return bool(raw)
    if isinstance(raw, str):
        return raw.strip().lower() in {"1", "true", "yes", "shadow"}
    return False
