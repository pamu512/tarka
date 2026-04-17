"""Optional HMAC request signing helpers (gateway or custom middleware).

Not used by DecisionClient by default — wire explicitly if your deployment validates
``X-Tarka-Timestamp`` + ``X-Tarka-Signature`` on the edge.
"""

from __future__ import annotations

import hashlib
import hmac
import time
from typing import Any


def build_signature_headers(
    body_bytes: bytes,
    *,
    secret: str,
    timestamp: int | None = None,
) -> dict[str, str]:
    """Return headers for HMAC-SHA256 over ``f\"{ts}\\n\".encode() + body``."""
    ts = str(timestamp if timestamp is not None else int(time.time()))
    msg = ts.encode("utf-8") + b"\n" + body_bytes
    sig = hmac.new(secret.encode("utf-8"), msg, hashlib.sha256).hexdigest()
    return {
        "X-Tarka-Timestamp": ts,
        "X-Tarka-Signature": sig,
    }


def verify_signature(
    body_bytes: bytes,
    headers: dict[str, Any],
    *,
    secret: str,
    max_skew_seconds: int = 300,
) -> bool:
    """Verify signature; returns False on missing/invalid headers."""
    ts_raw = headers.get("x-tarka-timestamp") or headers.get("X-Tarka-Timestamp")
    sig = headers.get("x-tarka-signature") or headers.get("X-Tarka-Signature")
    if not ts_raw or not sig:
        return False
    try:
        ts = int(str(ts_raw))
    except ValueError:
        return False
    now = int(time.time())
    if abs(now - ts) > max_skew_seconds:
        return False
    msg = str(ts).encode("utf-8") + b"\n" + body_bytes
    expected = hmac.new(secret.encode("utf-8"), msg, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, str(sig))
