"""Export recent ``audit_logs`` rows with PII masking for beta feedback bundles."""

from __future__ import annotations

import json
import os
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REDACTED = "[REDACTED]"


class ExportAuditError(RuntimeError):
    """Configuration or database errors for ``export-audit``."""

# Standard UUID (also matches transaction_id / case_id strings).
_UUID_RE = re.compile(
    r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b"
)


def _is_shadow_decision_dict(d: dict[str, Any]) -> bool:
    return (
        "reasoning" in d
        and isinstance(d.get("reasoning"), list)
        and "transaction_id" in d
        and "risk_score" in d
        and "is_fraud" in d
        and "confidence_metrics" in d
    )


def _is_transaction_schema_dict(d: dict[str, Any]) -> bool:
    return "entity_id" in d and "amount" in d and "timestamp" in d and "metadata" in d


def mask_transaction_schema(obj: dict[str, Any]) -> dict[str, Any]:
    """Redact ``entity_id``, ``timestamp``, and string ``metadata`` values; keep coarse structure."""
    out = dict(obj)
    out["entity_id"] = REDACTED
    out["timestamp"] = REDACTED
    meta = out.get("metadata")
    if isinstance(meta, dict):
        redacted_meta: dict[str, Any] = {}
        for k, v in meta.items():
            if isinstance(v, str):
                redacted_meta[k] = REDACTED
            elif isinstance(v, dict):
                redacted_meta[k] = {ik: (REDACTED if isinstance(iv, str) else iv) for ik, iv in v.items()}
            elif isinstance(v, list):
                redacted_meta[k] = [
                    REDACTED if isinstance(item, str) else item for item in v
                ]
            else:
                redacted_meta[k] = v
        out["metadata"] = redacted_meta
    return out


def mask_shadow_decision(obj: dict[str, Any]) -> dict[str, Any]:
    """Redact ``transaction_id`` only; preserve ``reasoning`` and other model fields verbatim."""
    out = dict(obj)
    out["transaction_id"] = REDACTED
    return out


def deep_mask_json(obj: Any) -> Any:
    """Recursively redact TransactionSchema-like blobs; preserve ShadowDecision ``reasoning``."""
    if isinstance(obj, dict):
        if _is_shadow_decision_dict(obj):
            return mask_shadow_decision(obj)
        if _is_transaction_schema_dict(obj):
            return mask_transaction_schema(obj)
        return {str(k): deep_mask_json(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [deep_mask_json(v) for v in obj]
    if isinstance(obj, str):
        stripped = obj.strip()
        if stripped.startswith(("{", "[")):
            try:
                parsed = json.loads(obj)
            except json.JSONDecodeError:
                pass
            else:
                masked_inner = deep_mask_json(parsed)
                return json.dumps(masked_inner, ensure_ascii=False, separators=(",", ":"))
        return _UUID_RE.sub(REDACTED, obj)
    return obj


def mask_action_taken(raw: str | None) -> str | None:
    """Mask JSON in ``action_taken`` (embeds ``transaction_id``)."""
    if raw is None or not raw.strip():
        return raw
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return _UUID_RE.sub(REDACTED, raw)
    if isinstance(data, dict):
        if "transaction_id" in data:
            data = dict(data)
            data["transaction_id"] = REDACTED
        return json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    return _UUID_RE.sub(REDACTED, raw)


def mask_agent_notes(raw: str | None) -> str | None:
    """Mask ShadowDecision JSON: redact ``transaction_id``, keep ``reasoning``."""
    if raw is None or not raw.strip():
        return raw
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return _UUID_RE.sub(REDACTED, raw)
    if isinstance(data, dict) and _is_shadow_decision_dict(data):
        return json.dumps(mask_shadow_decision(data), ensure_ascii=False)
    return json.dumps(deep_mask_json(data), ensure_ascii=False)


def _strip_uuids_in_strings(obj: Any) -> Any:
    """Catch UUIDs embedded in prompt ``content`` strings after structured masking."""
    if isinstance(obj, str):
        return _UUID_RE.sub(REDACTED, obj)
    if isinstance(obj, dict):
        return {k: _strip_uuids_in_strings(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_strip_uuids_in_strings(v) for v in obj]
    return obj


def mask_code_executed(raw: str | None) -> str | None:
    """Mask LLM message bundle (prompts may embed full ``TransactionSchema`` JSON)."""
    if raw is None or not raw.strip():
        return raw
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return _UUID_RE.sub(REDACTED, raw)
    masked = deep_mask_json(data)
    return json.dumps(_strip_uuids_in_strings(masked), ensure_ascii=False)


def mask_audit_row(row: dict[str, Any]) -> dict[str, Any]:
    """Apply masking to one ORM-shaped audit row dict."""
    case_id = row.get("case_id")
    case_out: str | Any = case_id
    if isinstance(case_id, str) and _UUID_RE.fullmatch(case_id):
        case_out = REDACTED
    ts = row.get("timestamp")
    ts_out: str | None
    if isinstance(ts, datetime):
        ts_out = ts.isoformat()
    elif ts is None:
        ts_out = None
    else:
        ts_out = str(ts)
    return {
        "id": row.get("id"),
        "case_id": case_out,
        "action_taken": mask_action_taken(row.get("action_taken")),
        "code_executed": mask_code_executed(row.get("code_executed")),
        "agent_notes": mask_agent_notes(row.get("agent_notes")),
        "timestamp": ts_out,
    }


def _async_to_sync_database_url(url: str) -> str:
    u = url.strip()
    if u.startswith("sqlite+aiosqlite"):
        return u.replace("sqlite+aiosqlite", "sqlite+pysqlite", 1)
    if u.startswith("postgresql+asyncpg"):
        return u.replace("postgresql+asyncpg", "postgresql+psycopg", 1)
    if u.startswith("postgres+asyncpg"):
        return u.replace("postgres+asyncpg", "postgresql+psycopg", 1)
    return u


def _database_url() -> str:
    raw = os.environ.get("TARKA_AUDIT_DATABASE_URL") or os.environ.get("SHADOW_DATABASE_URL", "").strip()
    if not raw:
        raise ExportAuditError(
            "Set SHADOW_DATABASE_URL or TARKA_AUDIT_DATABASE_URL to the Shadow audit database "
            "(SQLite file or Postgres URL)."
        )
    if ":memory:" in raw:
        raise ExportAuditError(
            "In-memory SQLite cannot be exported; use a file-based SQLite or Postgres URL."
        )
    return _async_to_sync_database_url(raw)


def run_export_audit(output: Path, *, limit: int = 100) -> None:
    """Fetch last ``limit`` ``audit_logs`` rows and write redacted JSON to ``output``."""
    try:
        from sqlalchemy import create_engine, text
    except ImportError as exc:
        raise ExportAuditError(
            "sqlalchemy is required for export-audit. Install the tarka package dependencies "
            "(``pip install -e .`` from repo root)."
        ) from exc

    url = _database_url()
    engine = create_engine(url, future=True)
    stmt = text(
        "SELECT id, case_id, action_taken, code_executed, agent_notes, timestamp "
        "FROM audit_logs ORDER BY id DESC LIMIT :lim"
    )
    rows_out: list[dict[str, Any]] = []
    try:
        with engine.connect() as conn:
            result = conn.execute(stmt, {"lim": limit})
            for row in result.mappings():
                rows_out.append(mask_audit_row(dict(row)))
    except ExportAuditError:
        raise
    except Exception as exc:
        raise ExportAuditError(f"Failed to read audit_logs: {exc}") from exc

    payload = {
        "exported_at": datetime.now(UTC).isoformat(),
        "database_url_host_redacted": REDACTED,
        "row_count": len(rows_out),
        "rows": rows_out,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
