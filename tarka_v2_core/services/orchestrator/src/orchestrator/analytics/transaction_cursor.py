"""Opaque keyset cursor for ``v_analytics_transactions`` (newest ``ts`` first)."""

from __future__ import annotations

import base64
import json
from typing import Any


def encode_transaction_cursor(*, ts: str, entity_id: str, amount: float) -> str:
    payload = {"ts": ts, "eid": entity_id, "amt": float(amount)}
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def decode_transaction_cursor(cursor: str | None) -> tuple[str, str, float] | None:
    if not cursor or not str(cursor).strip():
        return None
    pad = "=" * (-len(cursor) % 4)
    try:
        raw = base64.urlsafe_b64decode((cursor + pad).encode("ascii"))
        obj = json.loads(raw.decode("utf-8"))
    except (ValueError, json.JSONDecodeError, UnicodeDecodeError):
        return None
    if not isinstance(obj, dict):
        return None
    ts = obj.get("ts")
    eid = obj.get("eid")
    amt = obj.get("amt")
    if not isinstance(ts, str) or not ts.strip():
        return None
    if not isinstance(eid, str) or not eid.strip():
        return None
    if not isinstance(amt, (int, float)) or float(amt) != float(amt):
        return None
    return ts.strip(), eid.strip(), float(amt)
