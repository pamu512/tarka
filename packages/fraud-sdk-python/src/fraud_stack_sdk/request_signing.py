from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

"""Optional HMAC request signing helpers (gateway or decision-api middleware).

Implementation matches ``services/shared/tarka_request_signature.py`` when the
monorepo is on ``PYTHONPATH``; otherwise falls back to the same logic inline so
the published wheel stays self-contained.
"""
# Monorepo: prefer shared module (single source of truth)
_pkg_dir = Path(__file__).resolve().parents[4]
_shared = _pkg_dir / "services" / "shared"
if _shared.is_dir() and str(_shared) not in sys.path:
    sys.path.insert(0, str(_shared))

try:
    from tarka_request_signature import build_signature_headers as build_signature_headers
    from tarka_request_signature import verify_signature as verify_signature
except ImportError:
    import hashlib
    import hmac
    import time

    def build_signature_headers(
        body_bytes: bytes,
        *,
        secret: str,
        timestamp: int | None = None,
    ) -> dict[str, str]:
        """Return headers for HMAC-SHA256 over ``f\"{ts}\\n``.encode() + body``."""
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
