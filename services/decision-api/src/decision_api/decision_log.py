"""Canonical immutable decision log writer (OSS JSONL + optional warehouse sink)."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

from decision_api.config import settings

SCHEMA_ID = "tarka.decision_log/v1"


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
) -> dict[str, Any]:
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
        "payload_snapshot": payload_snapshot,
    }


async def emit_decision_log(record: dict[str, Any]) -> None:
    if not settings.decision_log_enabled:
        return
    await asyncio.to_thread(_write_jsonl_line, settings.decision_log_path, record)

    warehouse_url = settings.decision_log_warehouse_url.strip()
    if not warehouse_url:
        return

    headers: dict[str, str] = {"content-type": "application/json"}
    if settings.decision_log_warehouse_api_key.strip():
        headers["authorization"] = f"Bearer {settings.decision_log_warehouse_api_key.strip()}"
    async with httpx.AsyncClient(timeout=3.0) as client:
        await client.post(warehouse_url, json=record, headers=headers)
