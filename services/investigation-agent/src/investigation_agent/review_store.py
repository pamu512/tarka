from __future__ import annotations

import os
import threading
import time
from typing import Any, Literal

from investigation_agent.store_backend import StoreConnection, connect_store, init_postgres_schema

"""Human sign-off on copilot turns (sqlite file or shared Postgres schema)."""
_lock = threading.Lock()
_conn: StoreConnection | None = None


def _data_dir() -> str:
    d = os.environ.get("INVESTIGATION_DATA_DIR", "").strip()
    if not d:
        d = os.path.join(os.getcwd(), "var", "investigation-agent")
    os.makedirs(d, exist_ok=True)
    return d


def db_path() -> str:
    name = (
        os.environ.get("COPILOT_REVIEW_DB_NAME", "copilot_turn_reviews.sqlite3").strip()
        or "copilot_turn_reviews.sqlite3"
    )
    return os.path.join(_data_dir(), name)


def _get_conn() -> StoreConnection:
    global _conn
    with _lock:
        if _conn is None:
            _conn = connect_store(sqlite_path=db_path(), init_schema=_init_schema)
        return _conn


def _init_schema(c: StoreConnection) -> None:
    if c.dialect == "postgres":
        init_postgres_schema(c)
        return
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS copilot_turn_reviews (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            turn_id TEXT NOT NULL,
            tenant_id TEXT NOT NULL,
            analyst_id TEXT NOT NULL,
            status TEXT NOT NULL,
            note TEXT,
            created_at REAL NOT NULL
        )
        """
    )
    c.execute("CREATE INDEX IF NOT EXISTS idx_reviews_turn ON copilot_turn_reviews (turn_id)")
    c.execute(
        "CREATE INDEX IF NOT EXISTS idx_reviews_tenant_time ON copilot_turn_reviews (tenant_id, created_at DESC)"
    )
    c.commit()


def reset_connection_for_tests() -> None:
    global _conn
    with _lock:
        if _conn:
            _conn.close()
            _conn = None


def save_review(
    *,
    turn_id: str,
    tenant_id: str,
    analyst_id: str,
    status: Literal["approved", "rejected"],
    note: str | None,
) -> int:
    c = _get_conn()
    now = time.time()
    note_s = (note or "")[:2000] or None
    with _lock:
        cur = c.execute(
            """
            INSERT INTO copilot_turn_reviews (turn_id, tenant_id, analyst_id, status, note, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (turn_id, tenant_id, analyst_id, status, note_s, now),
        )
        c.commit()
        return int(cur.lastrowid or 0)


def latest_review(turn_id: str, tenant_id: str) -> dict[str, Any] | None:
    c = _get_conn()
    row = c.execute(
        """
        SELECT id, turn_id, tenant_id, analyst_id, status, note, created_at
        FROM copilot_turn_reviews
        WHERE turn_id = ? AND tenant_id = ?
        ORDER BY created_at DESC
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


def review_metrics(tenant_id: str, days: float = 30.0) -> dict[str, Any]:
    c = _get_conn()
    now = time.time()
    window_days = max(0.5, min(float(days), 365.0))
    since = now - (window_days * 86400.0)
    rows = c.execute(
        """
        SELECT status, COUNT(*) AS n
        FROM copilot_turn_reviews
        WHERE tenant_id = ? AND created_at >= ?
        GROUP BY status
        """,
        (tenant_id, since),
    ).fetchall()
    by_status = {str(r[0]): int(r[1]) for r in rows}
    total = int(sum(by_status.values()))
    approved = int(by_status.get("approved", 0))
    rejected = int(by_status.get("rejected", 0))
    approval_rate = (approved / total) if total > 0 else None

    uniq = c.execute(
        """
        SELECT COUNT(DISTINCT analyst_id)
        FROM copilot_turn_reviews
        WHERE tenant_id = ? AND created_at >= ?
        """,
        (tenant_id, since),
    ).fetchone()
    unique_reviewers = int(uniq[0] or 0) if uniq else 0
    return {
        "tenant_id": tenant_id,
        "window_days": window_days,
        "total_reviews": total,
        "approved": approved,
        "rejected": rejected,
        "approval_rate": approval_rate,
        "unique_reviewers": unique_reviewers,
        "by_status": by_status,
    }
