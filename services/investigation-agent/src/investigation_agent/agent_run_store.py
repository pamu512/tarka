from __future__ import annotations

import hashlib
import json
import logging
import os
import sqlite3
import threading
import time
from contextlib import suppress
from pathlib import Path
from typing import Any, Literal

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


def legacy_review_db_path() -> Path:
    name = (
        os.environ.get("COPILOT_REVIEW_DB_NAME", "copilot_turn_reviews.sqlite3").strip()
        or "copilot_turn_reviews.sqlite3"
    )
    return _data_dir() / name


def _review_digest(
    *,
    turn_id: str,
    tenant_id: str,
    analyst_id: str,
    status: str,
    note: str | None,
    source_event_id: str | None = None,
    previous_event_id: int | None = None,
) -> str:
    identity: dict[str, Any] = {
        "turn_id": str(turn_id),
        "tenant_id": str(tenant_id),
        "analyst_id": str(analyst_id),
        "status": str(status),
        "note": str(note) if note is not None else None,
    }
    if source_event_id is not None:
        identity["source_event_id"] = str(source_event_id)
    if previous_event_id is not None:
        identity["previous_event_id"] = int(previous_event_id)
    encoded = json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _legacy_review_rows() -> list[tuple[str, str, str, str, str, str | None, float, float]]:
    path = legacy_review_db_path()
    if not path.is_file() or path.resolve() == db_path().resolve():
        return []
    legacy = sqlite3.connect(path)
    try:
        table = legacy.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'copilot_turn_reviews'"
        ).fetchone()
        if not table:
            raise AgentRunPersistenceError("legacy review database has no review table")
        columns = {
            str(row[1])
            for row in legacy.execute("PRAGMA table_info(copilot_turn_reviews)").fetchall()
        }
        required = {
            "id",
            "turn_id",
            "tenant_id",
            "analyst_id",
            "status",
            "note",
            "created_at",
        }
        if not required <= columns:
            raise AgentRunPersistenceError("legacy review database schema is incomplete")
        updated_expr = "updated_at" if "updated_at" in columns else "created_at"
        rows = legacy.execute(
            "SELECT id, turn_id, tenant_id, analyst_id, status, note, created_at, "
            f"{updated_expr} FROM copilot_turn_reviews "
            "ORDER BY created_at ASC, id ASC"
        ).fetchall()
    finally:
        legacy.close()

    events: list[tuple[str, str, str, str, str, str | None, float, float]] = []
    for row in rows:
        status = str(row[4])
        if status not in {"approved", "rejected"}:
            raise AgentRunPersistenceError("legacy review status is invalid")
        turn_id = str(row[1])
        tenant_id = str(row[2])
        analyst_id = str(row[3])
        note = str(row[5]) if row[5] is not None else None
        created_at = float(row[6])
        events.append(
            (
                _review_digest(
                    turn_id=turn_id,
                    tenant_id=tenant_id,
                    analyst_id=analyst_id,
                    status=status,
                    note=note,
                    source_event_id=f"legacy:{int(row[0])}",
                ),
                turn_id,
                tenant_id,
                analyst_id,
                status,
                note,
                created_at,
                float(row[7]),
            )
        )
    return events


def _create_review_history_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS copilot_turn_reviews (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_digest TEXT NOT NULL UNIQUE,
            turn_id TEXT NOT NULL,
            tenant_id TEXT NOT NULL,
            analyst_id TEXT NOT NULL,
            status TEXT NOT NULL,
            note TEXT,
            created_at REAL NOT NULL,
            updated_at REAL NOT NULL
        )
        """
    )


def _upgrade_review_history_table(conn: sqlite3.Connection) -> set[int]:
    migrated_current_ids: set[int] = set()
    table = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'copilot_turn_reviews'"
    ).fetchone()
    if not table:
        _create_review_history_table(conn)
    else:
        columns = {
            str(row[1])
            for row in conn.execute("PRAGMA table_info(copilot_turn_reviews)").fetchall()
        }
        if "event_digest" not in columns:
            rows = conn.execute(
                """
                SELECT id, turn_id, tenant_id, analyst_id, status, note,
                       created_at, updated_at
                FROM copilot_turn_reviews
                ORDER BY created_at ASC, id ASC
                """
            ).fetchall()
            conn.execute(
                "ALTER TABLE copilot_turn_reviews RENAME TO copilot_turn_reviews_pre_history"
            )
            _create_review_history_table(conn)
            conn.executemany(
                """
                INSERT OR IGNORE INTO copilot_turn_reviews (
                    event_digest, turn_id, tenant_id, analyst_id, status, note,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        _review_digest(
                            turn_id=str(row[1]),
                            tenant_id=str(row[2]),
                            analyst_id=str(row[3]),
                            status=str(row[4]),
                            note=str(row[5]) if row[5] is not None else None,
                            source_event_id=f"unified:{int(row[0])}",
                        ),
                        str(row[1]),
                        str(row[2]),
                        str(row[3]),
                        str(row[4]),
                        str(row[5]) if row[5] is not None else None,
                        float(row[6]),
                        float(row[7]),
                    )
                    for row in rows
                ],
            )
            migrated_current_ids = {
                int(row[0])
                for row in conn.execute("SELECT id FROM copilot_turn_reviews").fetchall()
            }
            conn.execute("DROP TABLE copilot_turn_reviews_pre_history")
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_reviews_tenant_time "
        "ON copilot_turn_reviews (tenant_id, created_at DESC)"
    )
    return migrated_current_ids


def _import_legacy_review_rows(
    conn: sqlite3.Connection,
    legacy_rows: list[tuple[str, str, str, str, str, str | None, float, float]],
    *,
    migrated_current_ids: set[int],
) -> None:
    unmatched_current_ids = set(migrated_current_ids)
    for row in legacy_rows:
        event_digest, turn_id, tenant_id, analyst_id, status, note, created_at, updated_at = row
        matched = None
        if unmatched_current_ids:
            placeholders = ",".join("?" for _ in unmatched_current_ids)
            matched = conn.execute(
                f"""
                SELECT id
                FROM copilot_turn_reviews
                WHERE id IN ({placeholders})
                  AND turn_id = ? AND tenant_id = ? AND analyst_id = ?
                  AND status = ? AND note IS ? AND created_at = ?
                ORDER BY id ASC
                LIMIT 1
                """,
                (
                    *sorted(unmatched_current_ids),
                    turn_id,
                    tenant_id,
                    analyst_id,
                    status,
                    note,
                    created_at,
                ),
            ).fetchone()
        if matched:
            matched_id = int(matched[0])
            conn.execute(
                "UPDATE copilot_turn_reviews SET event_digest = ? WHERE id = ?",
                (event_digest, matched_id),
            )
            unmatched_current_ids.remove(matched_id)
            continue
        conn.execute(
            """
            INSERT OR IGNORE INTO copilot_turn_reviews (
                event_digest, turn_id, tenant_id, analyst_id, status,
                note, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event_digest,
                turn_id,
                tenant_id,
                analyst_id,
                status,
                note,
                created_at,
                updated_at,
            ),
        )


def _get_conn() -> sqlite3.Connection:
    global _conn
    with _lock:
        if _conn is None:
            legacy_rows = _legacy_review_rows()
            conn = sqlite3.connect(db_path(), check_same_thread=False)
            try:
                conn.execute("PRAGMA journal_mode=WAL")
                conn.execute("PRAGMA synchronous=FULL")
                conn.execute("BEGIN IMMEDIATE")
                conn.execute(
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
                conn.execute(
                    "CREATE UNIQUE INDEX IF NOT EXISTS idx_agent_runs_tenant_turn "
                    "ON copilot_agent_runs (tenant_id, turn_id)"
                )
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_agent_runs_tenant_created "
                    "ON copilot_agent_runs (tenant_id, created_at DESC)"
                )
                migrated_current_ids = _upgrade_review_history_table(conn)
                _import_legacy_review_rows(
                    conn,
                    legacy_rows,
                    migrated_current_ids=migrated_current_ids,
                )
                conn.commit()
            except Exception:
                if conn.in_transaction:
                    conn.rollback()
                conn.close()
                raise
            _conn = conn
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


def _insert_agent_run(
    conn: sqlite3.Connection,
    payload: dict[str, Any],
    *,
    analyst_id: str,
    turn_id: str,
    ignore_existing: bool,
) -> None:
    run = _validated_payload(payload)
    blob = json.dumps(run, sort_keys=True, separators=(",", ":"), default=str)
    mode = "INSERT OR IGNORE" if ignore_existing else "INSERT"
    changed = conn.execute(
        f"""
        {mode} INTO copilot_agent_runs (
            agent_run_id, tenant_id, analyst_id, turn_id, prompt_hash,
            model_provider, model_revision, review_state, payload_json, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            str(run["agent_run_id"]),
            str(run["tenant_id"]),
            str(analyst_id),
            str(turn_id),
            str(run["prompt_hash"]),
            str(run["model_provider"]),
            str(run["model_revision"]),
            str(run["review_state"]),
            blob,
            str(run["created_at"]),
        ),
    )
    if ignore_existing and changed.rowcount == 0:
        existing = conn.execute(
            """
            SELECT agent_run_id
            FROM copilot_agent_runs
            WHERE tenant_id = ? AND turn_id = ?
            """,
            (str(run["tenant_id"]), str(turn_id)),
        ).fetchone()
        if not existing or str(existing[0]) != str(run["agent_run_id"]):
            raise AgentRunPersistenceError(
                "emergency AgentRun conflicts with persisted tenant turn"
            )


def _persist_sqlite(
    payload: dict[str, Any],
    *,
    analyst_id: str,
    turn_id: str,
) -> None:
    conn = _get_conn()
    with _lock:
        _insert_agent_run(
            conn,
            payload,
            analyst_id=analyst_id,
            turn_id=turn_id,
            ignore_existing=False,
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
    record = _load_emergency_record(
        tenant_id=tenant_id,
        agent_run_id=agent_run_id,
        turn_id=turn_id,
    )
    run = record.get("agent_run") if isinstance(record, dict) else None
    if not isinstance(run, dict):
        return None
    conn = None
    try:
        conn = _get_conn()
        with _lock:
            conn.execute("BEGIN IMMEDIATE")
            _insert_agent_run(
                conn,
                run,
                analyst_id=str(record.get("analyst_id") or ""),
                turn_id=str(record.get("turn_id") or turn_id or ""),
                ignore_existing=True,
            )
            conn.commit()
    except Exception:
        with suppress(Exception):
            if conn is not None and conn.in_transaction:
                conn.rollback()
        log.exception(
            "agent_run_emergency_rehydrate_failed tenant_id=%s agent_run_id=%s turn_id=%s",
            tenant_id,
            agent_run_id,
            turn_id,
        )
    return run


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


def _update_agent_run_review_payload(
    conn: sqlite3.Connection,
    *,
    tenant_id: str,
    turn_id: str,
    review_state: str,
) -> None:
    row = conn.execute(
        "SELECT payload_json FROM copilot_agent_runs WHERE tenant_id = ? AND turn_id = ?",
        (tenant_id, turn_id),
    ).fetchone()
    if not row:
        raise AgentRunPersistenceError("AgentRun is absent from SQLite")
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
    changed = conn.execute(
        """
        UPDATE copilot_agent_runs
        SET review_state = ?, payload_json = ?
        WHERE tenant_id = ? AND turn_id = ?
        """,
        (review_state, blob, tenant_id, turn_id),
    )
    if changed.rowcount != 1:
        raise AgentRunPersistenceError("AgentRun review update did not affect one row")


def _append_review_event(
    conn: sqlite3.Connection,
    *,
    turn_id: str,
    tenant_id: str,
    analyst_id: str,
    status: str,
    note: str | None,
    created_at: float,
) -> tuple[int, bool]:
    latest = conn.execute(
        """
        SELECT id, analyst_id, status, note
        FROM copilot_turn_reviews
        WHERE turn_id = ? AND tenant_id = ?
        ORDER BY created_at DESC, id DESC
        LIMIT 1
        """,
        (turn_id, tenant_id),
    ).fetchone()
    if latest and (
        str(latest[1]) == analyst_id
        and str(latest[2]) == status
        and (str(latest[3]) if latest[3] is not None else None) == note
    ):
        return int(latest[0]), False

    event_digest = _review_digest(
        turn_id=turn_id,
        tenant_id=tenant_id,
        analyst_id=analyst_id,
        status=status,
        note=note,
        previous_event_id=int(latest[0]) if latest else None,
    )
    inserted = conn.execute(
        """
        INSERT OR IGNORE INTO copilot_turn_reviews (
            event_digest, turn_id, tenant_id, analyst_id, status, note,
            created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            event_digest,
            turn_id,
            tenant_id,
            analyst_id,
            status,
            note,
            created_at,
            created_at,
        ),
    )
    row = conn.execute(
        "SELECT id FROM copilot_turn_reviews WHERE event_digest = ?",
        (event_digest,),
    ).fetchone()
    if not row:
        raise AgentRunPersistenceError("review event insert did not return a row")
    return int(row[0]), inserted.rowcount == 1


def save_review_transactionally(
    *,
    turn_id: str,
    tenant_id: str,
    analyst_id: str,
    status: Literal["approved", "rejected"],
    note: str | None,
) -> int:
    """Append one review event and update AgentRun state in one transaction."""
    if status not in {"approved", "rejected"}:
        raise AgentRunPersistenceError("review status must be approved or rejected")
    emergency_record = _load_emergency_record(
        tenant_id=tenant_id,
        agent_run_id=None,
        turn_id=turn_id,
    )
    conn = _get_conn()
    now = time.time()
    note_s = (note or "")[:2000] or None
    try:
        with _lock:
            conn.execute("BEGIN IMMEDIATE")
            existing_run = conn.execute(
                """
                SELECT 1 FROM copilot_agent_runs
                WHERE tenant_id = ? AND turn_id = ?
                """,
                (tenant_id, turn_id),
            ).fetchone()
            if not existing_run:
                emergency_run = (
                    emergency_record.get("agent_run")
                    if isinstance(emergency_record, dict)
                    else None
                )
                if not isinstance(emergency_run, dict):
                    raise AgentRunPersistenceError(
                        "AgentRun is absent from SQLite and emergency audit"
                    )
                _insert_agent_run(
                    conn,
                    emergency_run,
                    analyst_id=str(emergency_record.get("analyst_id") or ""),
                    turn_id=turn_id,
                    ignore_existing=True,
                )
            review_id, _inserted = _append_review_event(
                conn,
                turn_id=turn_id,
                tenant_id=tenant_id,
                analyst_id=analyst_id,
                status=status,
                note=note_s,
                created_at=now,
            )
            _update_agent_run_review_payload(
                conn,
                tenant_id=tenant_id,
                turn_id=turn_id,
                review_state=status,
            )
            conn.commit()
            return review_id
    except Exception as exc:
        with _lock:
            if conn.in_transaction:
                conn.rollback()
        if isinstance(exc, AgentRunPersistenceError):
            raise
        raise AgentRunPersistenceError("review and AgentRun transaction failed") from exc


def save_review_record(
    *,
    turn_id: str,
    tenant_id: str,
    analyst_id: str,
    status: Literal["approved", "rejected"],
    note: str | None,
) -> int:
    """Compatibility helper that appends a deduplicated review event."""
    if status not in {"approved", "rejected"}:
        raise AgentRunPersistenceError("review status must be approved or rejected")
    conn = _get_conn()
    now = time.time()
    note_s = (note or "")[:2000] or None
    try:
        with _lock:
            conn.execute("BEGIN IMMEDIATE")
            review_id, _inserted = _append_review_event(
                conn,
                turn_id=turn_id,
                tenant_id=tenant_id,
                analyst_id=analyst_id,
                status=status,
                note=note_s,
                created_at=now,
            )
            conn.commit()
            return review_id
    except Exception as exc:
        with _lock:
            if conn.in_transaction:
                conn.rollback()
        if isinstance(exc, AgentRunPersistenceError):
            raise
        raise AgentRunPersistenceError("review event transaction failed") from exc


def latest_review(turn_id: str, tenant_id: str) -> dict[str, Any] | None:
    conn = _get_conn()
    with _lock:
        row = conn.execute(
            """
            SELECT id, turn_id, tenant_id, analyst_id, status, note, created_at
            FROM copilot_turn_reviews
            WHERE turn_id = ? AND tenant_id = ?
            ORDER BY created_at DESC, id DESC
            LIMIT 1
            """,
            (turn_id, tenant_id),
        ).fetchone()
    if not row:
        return None
    return {
        "id": row[0],
        "turn_id": row[1],
        "tenant_id": row[2],
        "analyst_id": row[3],
        "status": row[4],
        "note": row[5],
        "created_at": row[6],
    }


def review_history(
    turn_id: str,
    tenant_id: str,
    *,
    limit: int = 100,
) -> list[dict[str, Any]]:
    conn = _get_conn()
    bounded_limit = max(1, min(int(limit), 500))
    with _lock:
        rows = conn.execute(
            """
            SELECT id, turn_id, tenant_id, analyst_id, status, note, created_at
            FROM copilot_turn_reviews
            WHERE turn_id = ? AND tenant_id = ?
            ORDER BY created_at DESC, id DESC
            LIMIT ?
            """,
            (turn_id, tenant_id, bounded_limit),
        ).fetchall()
    return [
        {
            "id": row[0],
            "turn_id": row[1],
            "tenant_id": row[2],
            "analyst_id": row[3],
            "status": row[4],
            "note": row[5],
            "created_at": row[6],
        }
        for row in rows
    ]


def review_metrics(tenant_id: str, days: float = 30.0) -> dict[str, Any]:
    conn = _get_conn()
    window_days = max(0.5, min(float(days), 365.0))
    since = time.time() - (window_days * 86400.0)
    with _lock:
        rows = conn.execute(
            """
            SELECT status, COUNT(*) AS n
            FROM copilot_turn_reviews
            WHERE tenant_id = ? AND created_at >= ?
            GROUP BY status
            """,
            (tenant_id, since),
        ).fetchall()
        uniq = conn.execute(
            """
            SELECT COUNT(DISTINCT analyst_id)
            FROM copilot_turn_reviews
            WHERE tenant_id = ? AND created_at >= ?
            """,
            (tenant_id, since),
        ).fetchone()
    by_status = {str(row[0]): int(row[1]) for row in rows}
    total = sum(by_status.values())
    approved = int(by_status.get("approved", 0))
    rejected = int(by_status.get("rejected", 0))
    return {
        "tenant_id": tenant_id,
        "window_days": window_days,
        "total_reviews": total,
        "approved": approved,
        "rejected": rejected,
        "approval_rate": (approved / total) if total else None,
        "unique_reviewers": int(uniq[0] or 0) if uniq else 0,
        "by_status": by_status,
    }
