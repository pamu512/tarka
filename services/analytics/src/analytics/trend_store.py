"""SQLite persistence for trend triage tickets + draft rules (+ HIL overrides).

Postgres schema lives in migrations/20260603_003_trend_agent_persistence.sql.
Offline/default path uses SQLite under TREND_AGENT_DATA_DIR (no live tenants required).
"""

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
    d = os.environ.get("TREND_AGENT_DATA_DIR", "").strip()
    if not d:
        d = os.path.join(os.getcwd(), "var", "trend-agent")
    os.makedirs(d, exist_ok=True)
    return d


def db_path() -> str:
    name = (
        os.environ.get("TREND_AGENT_DB_NAME", "trend_agent.sqlite3").strip()
        or "trend_agent.sqlite3"
    )
    return os.path.join(_data_dir(), name)


def _get_conn() -> sqlite3.Connection:
    global _conn
    with _lock:
        if _conn is None:
            _conn = sqlite3.connect(db_path(), check_same_thread=False)
            _conn.execute("PRAGMA journal_mode=WAL")
            _conn.execute("PRAGMA synchronous=NORMAL")
            _init_schema(_conn)
        return _conn


def _init_schema(c: sqlite3.Connection) -> None:
    c.executescript(
        """
        CREATE TABLE IF NOT EXISTS trend_triage_tickets (
            id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL,
            entity_id TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'OPEN',
            max_z_score REAL,
            envelope_json TEXT NOT NULL,
            rag_matrix_json TEXT NOT NULL,
            created_at REAL NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_trend_triage_tenant_entity
            ON trend_triage_tickets (tenant_id, entity_id, created_at DESC);

        CREATE TABLE IF NOT EXISTS trend_draft_rules (
            id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL,
            entity_id TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'PENDING_VALIDATION',
            rule_package_json TEXT NOT NULL,
            envelope_json TEXT NOT NULL,
            created_at REAL NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_trend_draft_tenant_status
            ON trend_draft_rules (tenant_id, status, created_at DESC);

        CREATE TABLE IF NOT EXISTS hil_context_overrides (
            id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL,
            entity_id TEXT NOT NULL,
            override_type TEXT NOT NULL,
            scope_key TEXT,
            analyst_rationale TEXT,
            created_at REAL NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_hil_tenant_entity
            ON hil_context_overrides (tenant_id, entity_id, created_at DESC);

        CREATE TABLE IF NOT EXISTS trend_entity_watchlist (
            tenant_id TEXT NOT NULL,
            entity_id TEXT NOT NULL,
            reason TEXT NOT NULL DEFAULT '',
            updated_at REAL NOT NULL,
            PRIMARY KEY (tenant_id, entity_id)
        );
        CREATE INDEX IF NOT EXISTS idx_trend_watch_updated
            ON trend_entity_watchlist (updated_at DESC);

        CREATE TABLE IF NOT EXISTS trend_velocity_baselines (
            tenant_id TEXT NOT NULL,
            entity_id TEXT NOT NULL,
            metric_key TEXT NOT NULL,
            n INTEGER NOT NULL DEFAULT 0,
            ewma_mean REAL NOT NULL DEFAULT 0,
            ewma_var REAL NOT NULL DEFAULT 0,
            updated_at REAL NOT NULL,
            PRIMARY KEY (tenant_id, entity_id, metric_key)
        );
        """
    )
    c.commit()


def reset_connection_for_tests() -> None:
    global _conn
    with _lock:
        if _conn:
            _conn.close()
            _conn = None


def insert_triage_ticket(
    *,
    tenant_id: str,
    entity_id: str,
    max_z_score: float | None,
    envelope: dict[str, Any],
    rag_matrix: dict[str, Any],
    status: str = "OPEN",
) -> str:
    tid = str(uuid.uuid4())
    c = _get_conn()
    with _lock:
        c.execute(
            """
            INSERT INTO trend_triage_tickets
            (id, tenant_id, entity_id, status, max_z_score, envelope_json, rag_matrix_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                tid,
                tenant_id,
                entity_id,
                status,
                max_z_score,
                json.dumps(envelope, sort_keys=True, default=str),
                json.dumps(rag_matrix, sort_keys=True, default=str),
                time.time(),
            ),
        )
        c.commit()
    return tid


def insert_draft_rule(
    *,
    tenant_id: str,
    entity_id: str,
    rule_package: dict[str, Any],
    envelope: dict[str, Any],
    status: str = "PENDING_VALIDATION",
) -> str:
    # Never auto-PROMOTED from the agent path.
    if status not in ("PENDING_VALIDATION", "REJECTED"):
        status = "PENDING_VALIDATION"
    rid = str(uuid.uuid4())
    c = _get_conn()
    with _lock:
        c.execute(
            """
            INSERT INTO trend_draft_rules
            (id, tenant_id, entity_id, status, rule_package_json, envelope_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                rid,
                tenant_id,
                entity_id,
                status,
                json.dumps(rule_package, sort_keys=True, default=str),
                json.dumps(envelope, sort_keys=True, default=str),
                time.time(),
            ),
        )
        c.commit()
    return rid


def insert_hil_override(
    *,
    tenant_id: str,
    entity_id: str,
    override_type: str,
    scope_key: str = "",
    analyst_rationale: str = "",
) -> str:
    oid = str(uuid.uuid4())
    c = _get_conn()
    with _lock:
        c.execute(
            """
            INSERT INTO hil_context_overrides
            (id, tenant_id, entity_id, override_type, scope_key, analyst_rationale, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                oid,
                tenant_id,
                entity_id,
                override_type,
                scope_key,
                analyst_rationale,
                time.time(),
            ),
        )
        c.commit()
    return oid


def list_hil_overrides(*, tenant_id: str, entity_id: str) -> list[dict[str, Any]]:
    c = _get_conn()
    rows = c.execute(
        """
        SELECT override_type, scope_key, analyst_rationale, created_at
        FROM hil_context_overrides
        WHERE tenant_id = ? AND entity_id = ?
        ORDER BY created_at DESC LIMIT 50
        """,
        (tenant_id, entity_id),
    ).fetchall()
    return [
        {
            "override_type": r[0],
            "scope_key": r[1] or "",
            "analyst_rationale": r[2] or "",
            "created_at": r[3],
        }
        for r in rows
    ]


def list_open_triage(*, tenant_id: str, entity_id: str) -> list[dict[str, Any]]:
    c = _get_conn()
    rows = c.execute(
        """
        SELECT id, status, max_z_score, envelope_json, created_at
        FROM trend_triage_tickets
        WHERE tenant_id = ? AND entity_id = ? AND status = 'OPEN'
        ORDER BY created_at DESC LIMIT 20
        """,
        (tenant_id, entity_id),
    ).fetchall()
    return [
        {
            "id": r[0],
            "status": r[1],
            "max_z_score": r[2],
            "envelope": json.loads(r[3] or "{}"),
            "created_at": r[4],
        }
        for r in rows
    ]


def list_pending_drafts(*, tenant_id: str) -> list[dict[str, Any]]:
    c = _get_conn()
    rows = c.execute(
        """
        SELECT id, entity_id, status, rule_package_json, created_at
        FROM trend_draft_rules
        WHERE tenant_id = ? AND status = 'PENDING_VALIDATION'
        ORDER BY created_at DESC LIMIT 50
        """,
        (tenant_id,),
    ).fetchall()
    return [
        {
            "id": r[0],
            "entity_id": r[1],
            "status": r[2],
            "rule_package": json.loads(r[3] or "{}"),
            "created_at": r[4],
        }
        for r in rows
    ]


def get_draft_rule(*, tenant_id: str, draft_id: str) -> dict[str, Any] | None:
    c = _get_conn()
    row = c.execute(
        """
        SELECT id, entity_id, status, rule_package_json, envelope_json, created_at
        FROM trend_draft_rules
        WHERE tenant_id = ? AND id = ?
        LIMIT 1
        """,
        (tenant_id, draft_id),
    ).fetchone()
    if not row:
        return None
    return {
        "id": row[0],
        "entity_id": row[1],
        "status": row[2],
        "rule_package": json.loads(row[3] or "{}"),
        "envelope": json.loads(row[4] or "{}"),
        "created_at": row[5],
    }


def reject_draft_rule(*, tenant_id: str, draft_id: str) -> dict[str, Any] | None:
    """HIL reject — only PENDING_VALIDATION → REJECTED. Never promotes."""
    row = get_draft_rule(tenant_id=tenant_id, draft_id=draft_id)
    if row is None:
        return None
    if row["status"] != "PENDING_VALIDATION":
        return row
    c = _get_conn()
    with _lock:
        c.execute(
            """
            UPDATE trend_draft_rules
            SET status = 'REJECTED'
            WHERE tenant_id = ? AND id = ? AND status = 'PENDING_VALIDATION'
            """,
            (tenant_id, draft_id),
        )
        c.commit()
    return get_draft_rule(tenant_id=tenant_id, draft_id=draft_id)


def refuse_promote_draft(*, tenant_id: str, draft_id: str) -> dict[str, Any]:
    """Hard policy: trend drafts are never auto-promoted to live Wasm from this path."""
    row = get_draft_rule(tenant_id=tenant_id, draft_id=draft_id)
    return {
        "ok": False,
        "error": "never_auto_promote",
        "detail": "Trend drafts stay PENDING_VALIDATION until a separate HIL promote path exists.",
        "draft": row,
        "wasm_ready": False,
    }


def baseline_min_n() -> int:
    return _baseline_min_n()


def _baseline_min_n() -> int:
    raw = (os.environ.get("TREND_BASELINE_MIN_N") or "3").strip()
    try:
        return max(2, int(raw))
    except ValueError:
        return 3


def _ewma_alpha() -> float:
    raw = (os.environ.get("TREND_BASELINE_EWMA_ALPHA") or "0.2").strip()
    try:
        a = float(raw)
    except ValueError:
        return 0.2
    return min(0.9, max(0.05, a))


def upsert_watch(*, tenant_id: str, entity_id: str, reason: str = "") -> None:
    tid = (tenant_id or "").strip()
    eid = (entity_id or "").strip()
    if not tid or not eid:
        return
    c = _get_conn()
    with _lock:
        c.execute(
            """
            INSERT INTO trend_entity_watchlist (tenant_id, entity_id, reason, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(tenant_id, entity_id) DO UPDATE SET
              reason = excluded.reason,
              updated_at = excluded.updated_at
            """,
            (tid, eid, (reason or "")[:256], time.time()),
        )
        c.commit()


def list_watch(*, tenant_id: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
    lim = max(1, min(int(limit or 50), 200))
    c = _get_conn()
    if tenant_id and tenant_id.strip():
        rows = c.execute(
            """
            SELECT tenant_id, entity_id, reason, updated_at
            FROM trend_entity_watchlist
            WHERE tenant_id = ?
            ORDER BY updated_at DESC LIMIT ?
            """,
            (tenant_id.strip(), lim),
        ).fetchall()
    else:
        rows = c.execute(
            """
            SELECT tenant_id, entity_id, reason, updated_at
            FROM trend_entity_watchlist
            ORDER BY updated_at DESC LIMIT ?
            """,
            (lim,),
        ).fetchall()
    return [
        {
            "tenant_id": r[0],
            "entity_id": r[1],
            "reason": r[2] or "",
            "updated_at": r[3],
        }
        for r in rows
    ]


def record_observation(
    *,
    tenant_id: str,
    entity_id: str,
    metric_key: str,
    observed: float,
) -> dict[str, Any]:
    """Update EWMA baseline for one metric. Returns snapshot after update."""
    tid = (tenant_id or "").strip()
    eid = (entity_id or "").strip()
    mk = (metric_key or "").strip()
    obs = float(observed)
    alpha = _ewma_alpha()
    c = _get_conn()
    with _lock:
        row = c.execute(
            """
            SELECT n, ewma_mean, ewma_var FROM trend_velocity_baselines
            WHERE tenant_id = ? AND entity_id = ? AND metric_key = ?
            """,
            (tid, eid, mk),
        ).fetchone()
        if row is None:
            n, mean, var = 1, obs, 0.0
        else:
            n_prev, mean_prev, var_prev = int(row[0]), float(row[1]), float(row[2])
            n = n_prev + 1
            if n_prev < 1:
                mean, var = obs, 0.0
            else:
                # EWMA mean + EWMA variance of residuals
                delta = obs - mean_prev
                mean = mean_prev + alpha * delta
                var = (1.0 - alpha) * (var_prev + alpha * delta * delta)
        c.execute(
            """
            INSERT INTO trend_velocity_baselines
              (tenant_id, entity_id, metric_key, n, ewma_mean, ewma_var, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(tenant_id, entity_id, metric_key) DO UPDATE SET
              n = excluded.n,
              ewma_mean = excluded.ewma_mean,
              ewma_var = excluded.ewma_var,
              updated_at = excluded.updated_at
            """,
            (tid, eid, mk, n, mean, var, time.time()),
        )
        c.commit()
    std = (var**0.5) if var > 0 else 0.0
    return {
        "metric_key": mk,
        "n": n,
        "ewma_mean": mean,
        "ewma_std": std,
        "ready": n >= _baseline_min_n(),
        "min_n": _baseline_min_n(),
    }


def baseline_snapshot(*, tenant_id: str, entity_id: str, metric_key: str) -> dict[str, Any] | None:
    c = _get_conn()
    row = c.execute(
        """
        SELECT n, ewma_mean, ewma_var FROM trend_velocity_baselines
        WHERE tenant_id = ? AND entity_id = ? AND metric_key = ?
        """,
        (tenant_id, entity_id, metric_key),
    ).fetchone()
    if not row:
        return None
    n, mean, var = int(row[0]), float(row[1]), float(row[2])
    std = (var**0.5) if var > 0 else 0.0
    return {
        "metric_key": metric_key,
        "n": n,
        "ewma_mean": mean,
        "ewma_std": std,
        "ready": n >= _baseline_min_n(),
        "min_n": _baseline_min_n(),
    }
