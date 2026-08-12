"""Durable AgentRun persistence (tenant-scoped SQLite under INVESTIGATION_DATA_DIR)."""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
import uuid
from typing import Any

_lock = threading.Lock()
_conn: sqlite3.Connection | None = None


def _data_dir() -> str:
    d = os.environ.get("INVESTIGATION_DATA_DIR", "").strip()
    if not d:
        d = os.path.join(os.getcwd(), "var", "investigation-agent")
    os.makedirs(d, exist_ok=True)
    return d


def db_path() -> str:
    name = (
        os.environ.get("COPILOT_AGENT_RUN_DB_NAME", "copilot_agent_runs.sqlite3").strip()
        or "copilot_agent_runs.sqlite3"
    )
    return os.path.join(_data_dir(), name)


def _get_conn() -> sqlite3.Connection:
    global _conn
    with _lock:
        if _conn is None:
            path = db_path()
            _conn = sqlite3.connect(path, check_same_thread=False)
            _conn.execute("PRAGMA journal_mode=WAL")
            _conn.execute("PRAGMA synchronous=NORMAL")
            _init_schema(_conn)
        return _conn


def _init_schema(c: sqlite3.Connection) -> None:
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS agent_runs (
            run_id TEXT PRIMARY KEY,
            turn_id TEXT NOT NULL,
            tenant_id TEXT NOT NULL,
            analyst_id TEXT NOT NULL,
            case_id TEXT,
            entity_ids_json TEXT,
            trace_ids_json TEXT,
            prompt_version TEXT,
            model TEXT,
            agent_build TEXT,
            tool_trace_redacted_json TEXT,
            claims_json TEXT,
            context_snapshot_json TEXT,
            created_at REAL NOT NULL
        )
        """
    )
    c.execute(
        "CREATE INDEX IF NOT EXISTS idx_agent_runs_turn ON agent_runs (tenant_id, turn_id, created_at DESC)"
    )
    c.execute(
        "CREATE INDEX IF NOT EXISTS idx_agent_runs_tenant_time ON agent_runs (tenant_id, created_at DESC)"
    )
    c.commit()


def reset_connection_for_tests() -> None:
    global _conn
    with _lock:
        if _conn:
            _conn.close()
            _conn = None


def _tool_trace_redacted(tool_calls: list[dict[str, Any]] | None) -> list[dict[str, str]]:
    import hashlib

    out: list[dict[str, str]] = []
    for t in tool_calls or []:
        if not isinstance(t, dict):
            continue
        name = t.get("tool")
        if not isinstance(name, str) or not name.strip():
            continue
        args = t.get("args") if isinstance(t.get("args"), dict) else {}
        payload = json.dumps(args or {}, sort_keys=True, default=str, separators=(",", ":"))
        digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        out.append({"tool": name.strip(), "args_sha256": digest})
    return out[:80]


def _normalize_claims(claims: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for c in claims or []:
        if not isinstance(c, dict):
            continue
        text = str(c.get("text") or "").strip()
        if not text:
            continue
        source = str(c.get("source") or "unknown").strip() or "unknown"
        eids = c.get("evidence_ids")
        if not isinstance(eids, list):
            eids = []
        out.append(
            {
                "text": text[:2000],
                "source": source[:32],
                "evidence_ids": [str(x).strip() for x in eids if str(x).strip()][:40],
            }
        )
    return out[:80]


def persist_agent_run(
    *,
    turn_id: str,
    tenant_id: str,
    analyst_id: str,
    case_id: str | None = None,
    entity_ids: list[str] | None = None,
    trace_ids: list[str] | None = None,
    prompt_version: str = "",
    model: str = "",
    agent_build: str = "",
    tool_calls: list[dict[str, Any]] | None = None,
    claims: list[dict[str, Any]] | None = None,
    context_snapshot: dict[str, Any] | None = None,
    run_id: str | None = None,
) -> str:
    rid = (run_id or "").strip() or str(uuid.uuid4())
    c = _get_conn()
    now = time.time()
    with _lock:
        c.execute(
            """
            INSERT OR REPLACE INTO agent_runs (
                run_id, turn_id, tenant_id, analyst_id, case_id,
                entity_ids_json, trace_ids_json, prompt_version, model, agent_build,
                tool_trace_redacted_json, claims_json, context_snapshot_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                rid,
                (turn_id or "").strip(),
                (tenant_id or "").strip(),
                (analyst_id or "").strip(),
                (case_id or None),
                json.dumps(list(entity_ids or []), separators=(",", ":")),
                json.dumps(list(trace_ids or []), separators=(",", ":")),
                (prompt_version or "")[:128],
                (model or "")[:128],
                (agent_build or "")[:128],
                json.dumps(_tool_trace_redacted(tool_calls), separators=(",", ":")),
                json.dumps(_normalize_claims(claims), separators=(",", ":")),
                json.dumps(context_snapshot or {}, sort_keys=True, default=str, separators=(",", ":")),
                now,
            ),
        )
        c.commit()
    return rid


def _row_to_dict(row: tuple[Any, ...]) -> dict[str, Any]:
    return {
        "run_id": row[0],
        "turn_id": row[1],
        "tenant_id": row[2],
        "analyst_id": row[3],
        "case_id": row[4],
        "entity_ids": json.loads(row[5] or "[]"),
        "trace_ids": json.loads(row[6] or "[]"),
        "prompt_version": row[7],
        "model": row[8],
        "agent_build": row[9],
        "tool_trace_redacted": json.loads(row[10] or "[]"),
        "claims": json.loads(row[11] or "[]"),
        "context_snapshot": json.loads(row[12] or "{}"),
        "created_at": row[13],
    }


_SELECT = """
    SELECT run_id, turn_id, tenant_id, analyst_id, case_id,
           entity_ids_json, trace_ids_json, prompt_version, model, agent_build,
           tool_trace_redacted_json, claims_json, context_snapshot_json, created_at
    FROM agent_runs
"""


def get_agent_run(*, run_id: str, tenant_id: str) -> dict[str, Any] | None:
    rid = (run_id or "").strip()
    tid = (tenant_id or "").strip()
    if not rid or not tid:
        return None
    c = _get_conn()
    row = c.execute(
        _SELECT + " WHERE run_id = ? AND tenant_id = ?",
        (rid, tid),
    ).fetchone()
    if not row:
        return None
    return _row_to_dict(row)


def list_agent_runs_for_turn(*, turn_id: str, tenant_id: str) -> list[dict[str, Any]]:
    turn = (turn_id or "").strip()
    tid = (tenant_id or "").strip()
    if not turn or not tid:
        return []
    c = _get_conn()
    rows = c.execute(
        _SELECT + " WHERE turn_id = ? AND tenant_id = ? ORDER BY created_at DESC LIMIT 20",
        (turn, tid),
    ).fetchall()
    return [_row_to_dict(r) for r in rows]
