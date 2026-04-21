"""Emitter targets with retry/backoff and failure visibility (#63)."""

from __future__ import annotations

import asyncio
import csv
import hashlib
import io
import json
import logging
from typing import Any, Callable

log = logging.getLogger("chitragupta.emitters")


def canonical_input_hash(payload: dict[str, Any]) -> str:
    body = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(body).hexdigest()


def emit_json(payload: dict[str, Any]) -> bytes:
    out = {"schema": "tarka.emitter.json/v1", "payload": payload}
    return json.dumps(out, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")


def emit_csv(payload: dict[str, Any]) -> bytes:
    rows = payload.get("rows")
    if not isinstance(rows, list) or not rows:
        rows = [{"metric": "value", "v": json.dumps(payload, sort_keys=True, default=str)}]
    buf = io.StringIO()
    fieldnames = sorted({k for r in rows if isinstance(r, dict) for k in r.keys()}) or ["col"]
    w = csv.DictWriter(buf, fieldnames=fieldnames, extrasaction="ignore")
    w.writeheader()
    for r in rows:
        if isinstance(r, dict):
            w.writerow({k: str(v) for k, v in r.items() if k in fieldnames})
    return buf.getvalue().encode("utf-8")


_EMITTERS: dict[str, Callable[[dict[str, Any]], bytes]] = {
    "json": emit_json,
    "csv": emit_csv,
}


def list_emitter_targets() -> list[str]:
    return sorted(_EMITTERS.keys())


async def emit_with_retry(
    name: str,
    payload: dict[str, Any],
    *,
    max_attempts: int,
    base_delay: float,
    attempt_hook: Callable[[int, str | None], None] | None = None,
    simulate_failures: int = 0,
) -> tuple[bytes, list[dict[str, Any]]]:
    """Run emitter ``name`` with exponential backoff; return (bytes, attempt_log)."""
    fn = _EMITTERS.get(name)
    if not fn:
        raise ValueError(f"unknown_emitter:{name}")
    log_entries: list[dict[str, Any]] = []
    last_err: str | None = None
    synthetic_left = max(0, int(simulate_failures))
    for attempt in range(1, max_attempts + 1):
        try:
            if synthetic_left > 0:
                synthetic_left -= 1
                raise RuntimeError("simulated_failure")
            data = fn(payload)
            log_entries.append({"attempt": attempt, "ok": True, "error": None})
            if attempt_hook:
                attempt_hook(attempt, None)
            return data, log_entries
        except Exception as e:
            last_err = str(e)
            log_entries.append({"attempt": attempt, "ok": False, "error": last_err})
            if attempt_hook:
                attempt_hook(attempt, last_err)
            if attempt >= max_attempts:
                break
            await asyncio.sleep(base_delay * (2 ** (attempt - 1)))
    raise RuntimeError(last_err or "emit_failed")
