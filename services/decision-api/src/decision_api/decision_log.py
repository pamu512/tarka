from __future__ import annotations

import asyncio
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

from decision_api.config import settings

"""Canonical immutable decision log writer (OSS JSONL + optional warehouse sink)."""
SCHEMA_ID = "tarka.decision_log/v1"
_SENSITIVE_KEYS = {
    "password",
    "passcode",
    "token",
    "secret",
    "api_key",
    "authorization",
    "cookie",
}


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _json_dumps(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _write_jsonl_line(path: str, payload: dict[str, Any]) -> None:
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("a", encoding="utf-8") as f:
        f.write(_json_dumps(payload))
        f.write("\n")


def _last_record_hash(path: str) -> str | None:
    out = Path(path)
    if not out.is_file():
        return None
    last_non_empty: str | None = None
    with out.open("r", encoding="utf-8") as f:
        for raw in f:
            line = raw.strip()
            if line:
                last_non_empty = line
    if not last_non_empty:
        return None
    try:
        parsed = json.loads(last_non_empty)
    except json.JSONDecodeError:
        return None
    if not isinstance(parsed, dict):
        return None
    val = parsed.get("record_hash")
    if isinstance(val, str) and val.strip():
        return val.strip()
    return None


def _record_hash(record: dict[str, Any]) -> str:
    return hashlib.sha256(_json_dumps(record).encode("utf-8")).hexdigest()


def _redact_sensitive(value: Any) -> Any:
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for key, raw in value.items():
            lk = str(key).strip().lower()
            if (
                lk in _SENSITIVE_KEYS
                or lk.endswith("_token")
                or lk.endswith("_secret")
                or lk.endswith("_key")
            ):
                out[key] = "[REDACTED]"
            else:
                out[key] = _redact_sensitive(raw)
        return out
    if isinstance(value, list):
        return [_redact_sensitive(item) for item in value]
    return value


def build_decision_log_record(
    *,
    trace_id: str,
    tenant_id: str,
    entity_id: str,
    event_type: str,
    decision: str,
    score: float,
    tags: list[str],
    rule_hits: list[str],
    reasons: list[str],
    ml_score: float | None,
    inference_context: dict[str, Any],
    recommended_action: str | None,
    challenge_policy_id: str | None,
    challenge_metadata: dict[str, Any] | None,
    fallback_reason: str | None,
    payload_snapshot: dict[str, Any],
    artifact_manifest: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = (
        payload_snapshot
        if settings.decision_log_include_payload_snapshot
        else {"omitted": True}
    )
    return {
        "schema_id": SCHEMA_ID,
        "logged_at": _utc_now_iso(),
        "trace_id": trace_id,
        "tenant_id": tenant_id,
        "entity_id": entity_id,
        "event_type": event_type,
        "decision": decision,
        "score": float(score),
        "tags": tags,
        "rule_hits": rule_hits,
        "reasons": reasons,
        "ml_score": ml_score,
        "inference_context": inference_context,
        "recommended_action": recommended_action,
        "challenge_policy_id": challenge_policy_id,
        "challenge_metadata": challenge_metadata or {},
        "fallback_reason": fallback_reason,
        "payload_snapshot": _redact_sensitive(payload),
        "artifact_manifest": artifact_manifest or {},
    }


async def emit_decision_log(record: dict[str, Any]) -> None:
    if not settings.decision_log_enabled:
        return
    prev_hash = await asyncio.to_thread(_last_record_hash, settings.decision_log_path)
    record_out = dict(record)
    if prev_hash:
        record_out["previous_record_hash"] = prev_hash
    record_out["record_hash"] = _record_hash(record_out)

    await asyncio.to_thread(_write_jsonl_line, settings.decision_log_path, record_out)

    warehouse_url = settings.decision_log_warehouse_url.strip()
    if not warehouse_url:
        return

    headers: dict[str, str] = {"content-type": "application/json"}
    if settings.decision_log_warehouse_api_key.strip():
        headers["authorization"] = (
            f"Bearer {settings.decision_log_warehouse_api_key.strip()}"
        )
    async with httpx.AsyncClient(timeout=3.0) as client:
        await client.post(warehouse_url, json=record_out, headers=headers)
