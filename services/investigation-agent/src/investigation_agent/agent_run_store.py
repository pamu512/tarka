from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
from pathlib import Path
from typing import Any

"""Durable tenant-scoped storage for every investigation AgentRun."""

_lock = threading.Lock()
_conn: sqlite3.Connection | None = None
log = logging.getLogger(__name__)


class AgentRunPersistenceError(RuntimeError):
    pass


def _data_dir() -> Path:
    raw = os.environ.get("INVESTIGATION_DATA_DIR", "").strip()
    path = Path(raw) if raw else Path.cwd() / "var" / "investigation-agent"
    path.mkdir(parents=True, exist_ok=True)
    return path


def db_path() -> Path:
    name = (
        os.environ.get("COPILOT_AGENT_RUN_DB_NAME", "copilot_agent_runs.sqlite3").strip()
        or "copilot_agent_runs.sqlite3"
    )
    return _data_dir() / name


def emergency_path() -> Path:
    return _data_dir() / "copilot_agent_runs.emergency.jsonl"


def _get_conn() -> sqlite3.Connection:
    global _conn
    with _lock:
        if _conn is None:
            _conn = sqlite3.connect(db_path(), check_same_thread=False)
            _conn.execute("PRAGMA journal_mode=WAL")
            _conn.execute("PRAGMA synchronous=FULL")
            _conn.execute(
                """
                CREATE TABLE IF NOT EXISTS copilot_agent_runs (
                    agent_run_id TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL,
                    analyst_id TEXT NOT NULL,
                    turn_id TEXT NOT NULL,
                    prompt_hash TEXT NOT NULL,
                    model_provider TEXT NOT NULL,
                    model_revision TEXT NOT NULL,
                    review_state TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            _conn.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_agent_runs_tenant_turn "
                "ON copilot_agent_runs (tenant_id, turn_id)"
            )
            _conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_agent_runs_tenant_created "
                "ON copilot_agent_runs (tenant_id, created_at DESC)"
            )
            _conn.commit()
        return _conn


def reset_connection_for_tests() -> None:
    global _conn
    with _lock:
        if _conn is not None:
            _conn.close()
            _conn = None


def _validated_payload(payload: dict[str, Any]) -> dict[str, Any]:
    required = (
        "agent_run_id",
        "tenant_id",
        "prompt_hash",
        "model_provider",
        "model_revision",
        "tool_calls",
        "evidence_ids",
        "concept_ids",
        "claims",
        "uncertainty",
        "review_state",
        "created_at",
    )
    missing = [key for key in required if key not in payload]
    if missing:
        raise AgentRunPersistenceError(f"AgentRun payload missing fields: {','.join(missing)}")
    return dict(payload)


def _persist_sqlite(
    payload: dict[str, Any],
    *,
    analyst_id: str,
    turn_id: str,
) -> None:
    conn = _get_conn()
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    with _lock:
        conn.execute(
            """
            INSERT INTO copilot_agent_runs (
                agent_run_id, tenant_id, analyst_id, turn_id, prompt_hash,
                model_provider, model_revision, review_state, payload_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(payload["agent_run_id"]),
                str(payload["tenant_id"]),
                str(analyst_id),
                str(turn_id),
                str(payload["prompt_hash"]),
                str(payload["model_provider"]),
                str(payload["model_revision"]),
                str(payload["review_state"]),
                blob,
                str(payload["created_at"]),
            ),
        )
        conn.commit()


def _persist_emergency(
    payload: dict[str, Any],
    *,
    analyst_id: str,
    turn_id: str,
    primary_error: Exception,
) -> None:
    record = {
        "agent_run": payload,
        "analyst_id": analyst_id,
        "turn_id": turn_id,
        "primary_error": type(primary_error).__name__,
    }
    line = (json.dumps(record, sort_keys=True, separators=(",", ":"), default=str) + "\n").encode(
        "utf-8"
    )
    fd = os.open(
        emergency_path(),
        os.O_APPEND | os.O_CREAT | os.O_WRONLY,
        0o600,
    )
    try:
        os.write(fd, line)
        os.fsync(fd)
    finally:
        os.close(fd)


def persist_agent_run(
    payload: dict[str, Any],
    *,
    analyst_id: str,
    turn_id: str,
) -> str:
    run = _validated_payload(payload)
    try:
        _persist_sqlite(run, analyst_id=analyst_id, turn_id=turn_id)
        return "persisted"
    except Exception as primary_error:
        try:
            _persist_emergency(
                run,
                analyst_id=analyst_id,
                turn_id=turn_id,
                primary_error=primary_error,
            )
            return "degraded_emergency"
        except Exception as emergency_error:
            raise AgentRunPersistenceError(
                "AgentRun persistence failed in SQLite and emergency audit log"
            ) from emergency_error


def _load_emergency_record(
    *,
    tenant_id: str,
    agent_run_id: str | None,
    turn_id: str | None,
) -> dict[str, Any] | None:
    path = emergency_path()
    if not path.is_file():
        return None
    for raw in reversed(path.read_text(encoding="utf-8").splitlines()):
        try:
            record = json.loads(raw)
        except json.JSONDecodeError:
            continue
        run = record.get("agent_run") if isinstance(record, dict) else None
        if not isinstance(run, dict) or str(run.get("tenant_id")) != tenant_id:
            continue
        if agent_run_id and str(run.get("agent_run_id")) != agent_run_id:
            continue
        if turn_id and str(record.get("turn_id")) != turn_id:
            continue
        return record
    return None


def _load_emergency(
    *,
    tenant_id: str,
    agent_run_id: str | None,
    turn_id: str | None,
) -> dict[str, Any] | None:
    record = _load_emergency_record(
        tenant_id=tenant_id,
        agent_run_id=agent_run_id,
        turn_id=turn_id,
    )
    run = record.get("agent_run") if isinstance(record, dict) else None
    return run if isinstance(run, dict) else None


def get_agent_run(
    *,
    tenant_id: str,
    agent_run_id: str | None = None,
    turn_id: str | None = None,
) -> dict[str, Any] | None:
    if not agent_run_id and not turn_id:
        raise ValueError("agent_run_id or turn_id is required")
    row = None
    try:
        conn = _get_conn()
        field = "agent_run_id" if agent_run_id else "turn_id"
        value = agent_run_id or turn_id
        with _lock:
            row = conn.execute(
                f"SELECT payload_json FROM copilot_agent_runs WHERE tenant_id = ? AND {field} = ?",
                (tenant_id, value),
            ).fetchone()
    except Exception:
        log.exception(
            "agent_run_sqlite_read_failed tenant_id=%s agent_run_id=%s turn_id=%s",
            tenant_id,
            agent_run_id,
            turn_id,
        )
        row = None
    if row:
        payload = json.loads(str(row[0]))
        return payload if isinstance(payload, dict) else None
    return _load_emergency(
        tenant_id=tenant_id,
        agent_run_id=agent_run_id,
        turn_id=turn_id,
    )


def update_review_state(*, tenant_id: str, turn_id: str, review_state: str) -> bool:
    try:
        conn = _get_conn()
        with _lock:
            row = conn.execute(
                "SELECT payload_json FROM copilot_agent_runs WHERE tenant_id = ? AND turn_id = ?",
                (tenant_id, turn_id),
            ).fetchone()
            if row:
                payload = json.loads(str(row[0]))
                if not isinstance(payload, dict):
                    raise AgentRunPersistenceError("stored AgentRun payload is invalid")
                payload["review_state"] = review_state
                blob = json.dumps(
                    payload,
                    sort_keys=True,
                    separators=(",", ":"),
                    default=str,
                )
                conn.execute(
                    """
                    UPDATE copilot_agent_runs
                    SET review_state = ?, payload_json = ?
                    WHERE tenant_id = ? AND turn_id = ?
                    """,
                    (review_state, blob, tenant_id, turn_id),
                )
                conn.commit()
                return True
        primary_error: Exception = AgentRunPersistenceError("AgentRun is absent from SQLite")
    except Exception as exc:
        log.exception(
            "agent_run_sqlite_review_update_failed tenant_id=%s turn_id=%s",
            tenant_id,
            turn_id,
        )
        primary_error = exc

    record = _load_emergency_record(
        tenant_id=tenant_id,
        agent_run_id=None,
        turn_id=turn_id,
    )
    run = record.get("agent_run") if isinstance(record, dict) else None
    if not isinstance(run, dict):
        return False
    updated = dict(run)
    updated["review_state"] = review_state
    _persist_emergency(
        updated,
        analyst_id=str(record.get("analyst_id") or ""),
        turn_id=turn_id,
        primary_error=primary_error,
    )
    return True
