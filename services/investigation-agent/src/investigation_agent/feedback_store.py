"""SQLite persistence for chat turns and analyst feedback (RAG / quality loop)."""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
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
    name = os.environ.get("COPILOT_FEEDBACK_DB_NAME", "copilot_feedback.sqlite3").strip() or "copilot_feedback.sqlite3"
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
        CREATE TABLE IF NOT EXISTS copilot_turns (
            turn_id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL,
            analyst_id TEXT NOT NULL,
            case_id TEXT,
            playbook_id TEXT,
            prompt_version TEXT,
            reply_preview TEXT,
            tool_count INTEGER NOT NULL DEFAULT 0,
            created_at REAL NOT NULL
        )
        """
    )
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS copilot_feedback (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            turn_id TEXT NOT NULL,
            tenant_id TEXT NOT NULL,
            analyst_id TEXT NOT NULL,
            rating INTEGER NOT NULL,
            note TEXT,
            claim_indices_json TEXT,
            tags_json TEXT,
            created_at REAL NOT NULL
        )
        """
    )
    c.execute("CREATE INDEX IF NOT EXISTS idx_fb_tenant_time ON copilot_feedback (tenant_id, created_at DESC)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_fb_turn ON copilot_feedback (turn_id)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_turns_scope ON copilot_turns (tenant_id, analyst_id, created_at DESC)")
    c.commit()
    _ensure_persona_column(c)


def _ensure_persona_column(c: sqlite3.Connection) -> None:
    rows = c.execute("PRAGMA table_info(copilot_turns)").fetchall()
    cols = {str(row[1]) for row in rows}
    if "persona" not in cols:
        c.execute("ALTER TABLE copilot_turns ADD COLUMN persona TEXT")
        c.commit()


def reset_connection_for_tests() -> None:
    global _conn
    with _lock:
        if _conn:
            _conn.close()
            _conn = None


def record_turn(
    *,
    turn_id: str,
    tenant_id: str,
    analyst_id: str,
    case_id: str | None,
    playbook_id: str | None,
    prompt_version: str,
    reply_preview: str,
    tool_count: int,
    persona: str | None = None,
) -> None:
    c = _get_conn()
    now = time.time()
    ps = (persona or "").strip()[:32] or None
    with _lock:
        c.execute(
            """
            INSERT OR REPLACE INTO copilot_turns
            (turn_id, tenant_id, analyst_id, case_id, playbook_id, prompt_version, reply_preview, tool_count, created_at, persona)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                turn_id,
                tenant_id,
                analyst_id,
                case_id,
                playbook_id,
                prompt_version,
                (reply_preview or "")[:2000],
                int(tool_count),
                now,
                ps,
            ),
        )
        c.commit()


def lookup_turn(turn_id: str) -> dict[str, Any] | None:
    c = _get_conn()
    row = c.execute(
        "SELECT turn_id, tenant_id, analyst_id, case_id, playbook_id, persona FROM copilot_turns WHERE turn_id = ?",
        (turn_id,),
    ).fetchone()
    if not row:
        return None
    return {
        "turn_id": row[0],
        "tenant_id": row[1],
        "analyst_id": row[2],
        "case_id": row[3],
        "playbook_id": row[4],
        "persona": row[5],
    }


def save_feedback(
    *,
    turn_id: str,
    tenant_id: str,
    analyst_id: str,
    rating: int,
    note: str | None,
    claim_indices: list[int] | None,
    tags: dict[str, Any] | None = None,
) -> int:
    c = _get_conn()
    now = time.time()
    ci = json.dumps(claim_indices[:40]) if claim_indices else None
    tj = json.dumps(tags) if tags else None
    note_s = (note or "")[:2000] or None
    with _lock:
        cur = c.execute(
            """
            INSERT INTO copilot_feedback
            (turn_id, tenant_id, analyst_id, rating, note, claim_indices_json, tags_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (turn_id, tenant_id, analyst_id, rating, note_s, ci, tj, now),
        )
        c.commit()
        return int(cur.lastrowid or 0)


def feedback_summary(tenant_id: str, days: float = 7.0) -> dict[str, Any]:
    c = _get_conn()
    cutoff = time.time() - max(0.5, days) * 86400
    rows = c.execute(
        """
        SELECT rating, COUNT(*) FROM copilot_feedback
        WHERE tenant_id = ? AND created_at >= ?
        GROUP BY rating
        """,
        (tenant_id, cutoff),
    ).fetchall()
    by_rating: dict[str, int] = {"-1": 0, "0": 0, "1": 0}
    total = 0
    for r, cnt in rows:
        key = str(int(r))
        if key in by_rating:
            by_rating[key] = int(cnt)
            total += int(cnt)
    avg_row = c.execute(
        """
        SELECT AVG(rating) FROM copilot_feedback
        WHERE tenant_id = ? AND created_at >= ?
        """,
        (tenant_id, cutoff),
    ).fetchone()
    avg = float(avg_row[0]) if avg_row and avg_row[0] is not None else None
    return {
        "tenant_id": tenant_id,
        "window_days": days,
        "total": total,
        "by_rating": by_rating,
        "avg_rating": round(avg, 4) if avg is not None else None,
    }


def list_recent_feedback(tenant_id: str, limit: int = 50) -> list[dict[str, Any]]:
    c = _get_conn()
    lim = max(1, min(limit, 200))
    rows = c.execute(
        """
        SELECT f.id, f.turn_id, f.analyst_id, f.rating, f.note, f.claim_indices_json, f.created_at,
               t.case_id, t.playbook_id, t.persona
        FROM copilot_feedback f
        LEFT JOIN copilot_turns t ON t.turn_id = f.turn_id
        WHERE f.tenant_id = ?
        ORDER BY f.created_at DESC
        LIMIT ?
        """,
        (tenant_id, lim),
    ).fetchall()
    out: list[dict[str, Any]] = []
    for row in rows:
        ci = row[5]
        try:
            claim_indices = json.loads(ci) if ci else None
        except json.JSONDecodeError:
            claim_indices = None
        out.append(
            {
                "id": row[0],
                "turn_id": row[1],
                "analyst_id": row[2],
                "rating": row[3],
                "note": row[4],
                "claim_indices": claim_indices,
                "created_at": row[6],
                "case_id": row[7],
                "playbook_id": row[8],
                "persona": row[9],
            },
        )
    return out
