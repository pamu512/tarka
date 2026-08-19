"""Shared investigation-agent persistence: sqlite (desk) or one Postgres schema.

Env:
  INVESTIGATION_STORE=sqlite|postgres  (default sqlite; local-sqlite is an alias)
  INVESTIGATION_DATABASE_URL or DATABASE_URL  (required when mode=postgres)

Helm maps dataPersistence.mode=postgres onto INVESTIGATION_STORE=postgres and
injects DATABASE_URL the same way core-api does. Fail closed if postgres is
selected and no URL is set.
"""

from __future__ import annotations

import os
import re
import sqlite3
import threading
from typing import Any, Literal
from urllib.parse import urlparse, urlunparse

StoreMode = Literal["sqlite", "postgres"]

_SCHEMA = "investigation_agent"

_UPSERT_PK = {
    "agent_runs": "run_id",
    "case_status_proposals": "proposal_id",
    "copilot_turns": "turn_id",
    "knowledge_chunks": "chunk_id",
}

_SERIAL_TABLES = frozenset({"copilot_feedback", "copilot_turn_reviews"})

_INSERT_OR_REPLACE = re.compile(
    r"INSERT\s+OR\s+REPLACE\s+INTO\s+(\w+)\s*\(([^)]+)\)",
    re.IGNORECASE | re.DOTALL,
)
_INSERT_INTO = re.compile(r"INSERT\s+INTO\s+(\w+)", re.IGNORECASE)
_PRAGMA_TABLE_INFO = re.compile(r"PRAGMA\s+table_info\(\s*(\w+)\s*\)", re.IGNORECASE)

_pg_schema_lock = threading.Lock()
_pg_schema_ready = False


class StoreMisconfigured(RuntimeError):
    """INVESTIGATION_STORE=postgres without a usable URL, or unknown mode."""


class _ExecResult:
    def __init__(self, rows: list[Any] | None = None, *, lastrowid: int = 0, inner: Any = None):
        self._rows = list(rows or [])
        self.lastrowid = lastrowid
        self._inner = inner

    def fetchone(self) -> Any:
        if self._rows:
            return self._rows.pop(0)
        if self._inner is not None:
            return self._inner.fetchone()
        return None

    def fetchall(self) -> list[Any]:
        if self._rows:
            rows, self._rows = self._rows, []
            return rows
        if self._inner is not None:
            return list(self._inner.fetchall())
        return []

    def __iter__(self):
        return iter(self.fetchall())


class StoreConnection:
    """sqlite3-shaped connection: execute/fetch/commit with ``?`` placeholders."""

    def __init__(self, raw: Any, dialect: StoreMode):
        self._raw = raw
        self.dialect = dialect
        self.lastrowid = 0

    def execute(self, sql: str, params: tuple[Any, ...] | list[Any] = ()) -> _ExecResult:
        text = (sql or "").strip()
        if self.dialect == "sqlite":
            cur = self._raw.execute(text, params)
            self.lastrowid = int(getattr(cur, "lastrowid", 0) or 0)
            return _ExecResult(lastrowid=self.lastrowid, inner=cur)
        return self._execute_postgres(text, tuple(params))

    def _execute_postgres(self, sql: str, params: tuple[Any, ...]) -> _ExecResult:
        pragma = _PRAGMA_TABLE_INFO.match(sql)
        if pragma:
            table = pragma.group(1)
            cur = self._raw.execute(
                """
                SELECT 0, column_name
                FROM information_schema.columns
                WHERE table_schema = %s AND table_name = %s
                ORDER BY ordinal_position
                """,
                (_SCHEMA, table),
            )
            rows = list(cur.fetchall())
            return _ExecResult(rows)

        upper = sql.upper()
        if upper.startswith("PRAGMA"):
            return _ExecResult()
        if upper in {"BEGIN IMMEDIATE", "BEGIN"}:
            # psycopg starts a transaction on the first statement.
            return _ExecResult()

        adapted = _adapt_insert_or_replace(sql)
        returning = False
        insert = _INSERT_INTO.match(adapted)
        if (
            insert
            and insert.group(1).lower() in _SERIAL_TABLES
            and "RETURNING" not in adapted.upper()
        ):
            adapted = adapted.rstrip().rstrip(";") + " RETURNING id"
            returning = True
        adapted = _qmark_to_percent(adapted)
        cur = self._raw.execute(adapted, params)
        lastrowid = 0
        leftover: list[Any] = []
        if returning:
            row = cur.fetchone()
            if row:
                lastrowid = int(row[0])
        self.lastrowid = lastrowid
        return _ExecResult(leftover, lastrowid=lastrowid, inner=cur)

    def commit(self) -> None:
        self._raw.commit()

    def rollback(self) -> None:
        self._raw.rollback()

    def close(self) -> None:
        self._raw.close()


def store_mode() -> StoreMode:
    raw = os.environ.get("INVESTIGATION_STORE", "").strip().lower()
    if raw in ("", "sqlite", "local-sqlite"):
        return "sqlite"
    if raw in ("postgres", "postgresql"):
        return "postgres"
    raise StoreMisconfigured(f"unknown INVESTIGATION_STORE={raw!r} (expected sqlite or postgres)")


def raw_postgres_url() -> str:
    for key in ("INVESTIGATION_DATABASE_URL", "DATABASE_URL"):
        val = (os.environ.get(key) or "").strip()
        if val:
            return val
    return ""


def normalize_postgres_url(url: str) -> str:
    text = (url or "").strip()
    for prefix in (
        "postgresql+asyncpg://",
        "postgresql+psycopg2://",
        "postgresql+psycopg://",
        "postgres+asyncpg://",
    ):
        if text.startswith(prefix):
            text = "postgresql://" + text.split("://", 1)[1]
            break
    return text


def resolved_postgres_url() -> str:
    return normalize_postgres_url(raw_postgres_url())


def postgres_url_configured() -> bool:
    url = resolved_postgres_url()
    if not url:
        return False
    parsed = urlparse(url)
    return parsed.scheme in {"postgres", "postgresql"} and bool(parsed.netloc or parsed.path)


def store_config_errors() -> list[str]:
    try:
        mode = store_mode()
    except StoreMisconfigured as exc:
        return [str(exc)]
    if mode == "postgres" and not postgres_url_configured():
        return [
            "INVESTIGATION_STORE=postgres requires INVESTIGATION_DATABASE_URL or DATABASE_URL",
        ]
    return []


def ensure_store_configured() -> None:
    errs = store_config_errors()
    if errs:
        raise StoreMisconfigured("; ".join(errs))


def public_database_url(url: str) -> str:
    """Mask password for logs / health (same idea as case-api)."""
    try:
        parsed = urlparse(url)
    except ValueError:
        return url
    if not parsed.password:
        return url
    netloc = parsed.netloc
    user = parsed.username or ""
    host = parsed.hostname or ""
    port = f":{parsed.port}" if parsed.port else ""
    auth = f"{user}:***@" if user else "***@"
    # urlparse may include user:pass@ in netloc; rebuild
    rebuilt = urlunparse(parsed._replace(netloc=f"{auth}{host}{port}"))
    return rebuilt if host else netloc.replace(parsed.password, "***")


def connect_sqlite(path: str) -> StoreConnection:
    raw = sqlite3.connect(path, check_same_thread=False)
    raw.execute("PRAGMA journal_mode=WAL")
    raw.execute("PRAGMA synchronous=NORMAL")
    return StoreConnection(raw, "sqlite")


def connect_postgres() -> StoreConnection:
    ensure_store_configured()
    url = resolved_postgres_url()
    try:
        import psycopg
    except ImportError as exc:
        raise StoreMisconfigured(
            "INVESTIGATION_STORE=postgres requires the psycopg package"
        ) from exc
    raw = psycopg.connect(url)
    raw.execute(f"CREATE SCHEMA IF NOT EXISTS {_SCHEMA}")
    raw.commit()
    raw.execute(f"SET search_path TO {_SCHEMA}, public")
    return StoreConnection(raw, "postgres")


def connect_store(*, sqlite_path: str, init_schema: Any) -> StoreConnection:
    """Open sqlite file or shared Postgres; run the store's schema initializer."""
    if store_mode() == "postgres":
        conn = connect_postgres()
    else:
        conn = connect_sqlite(sqlite_path)
    init_schema(conn)
    return conn


def init_postgres_schema(conn: StoreConnection) -> None:
    """Idempotent DDL for the four stores plus batch blobs in schema investigation_agent."""
    global _pg_schema_ready
    with _pg_schema_lock:
        sqls = (
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
                created_at DOUBLE PRECISION NOT NULL,
                source TEXT NOT NULL DEFAULT 'chat',
                decision_external_id TEXT
            )
            """,
            "CREATE INDEX IF NOT EXISTS idx_agent_runs_turn ON agent_runs (tenant_id, turn_id, created_at DESC)",
            "CREATE INDEX IF NOT EXISTS idx_agent_runs_tenant_time ON agent_runs (tenant_id, created_at DESC)",
            """
            CREATE TABLE IF NOT EXISTS case_status_proposals (
                proposal_id TEXT PRIMARY KEY,
                tenant_id TEXT NOT NULL,
                case_id TEXT NOT NULL,
                agent_run_id TEXT NOT NULL,
                from_status TEXT NOT NULL,
                to_status TEXT NOT NULL,
                reason_code TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                created_at DOUBLE PRECISION NOT NULL
            )
            """,
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
                created_at DOUBLE PRECISION NOT NULL,
                persona TEXT,
                workflow_id TEXT
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS copilot_feedback (
                id BIGSERIAL PRIMARY KEY,
                turn_id TEXT NOT NULL,
                tenant_id TEXT NOT NULL,
                analyst_id TEXT NOT NULL,
                rating INTEGER NOT NULL,
                note TEXT,
                claim_indices_json TEXT,
                tags_json TEXT,
                created_at DOUBLE PRECISION NOT NULL
            )
            """,
            "CREATE INDEX IF NOT EXISTS idx_fb_tenant_time ON copilot_feedback (tenant_id, created_at DESC)",
            "CREATE INDEX IF NOT EXISTS idx_fb_turn ON copilot_feedback (turn_id)",
            "CREATE INDEX IF NOT EXISTS idx_turns_scope ON copilot_turns (tenant_id, analyst_id, created_at DESC)",
            """
            CREATE TABLE IF NOT EXISTS copilot_turn_reviews (
                id BIGSERIAL PRIMARY KEY,
                turn_id TEXT NOT NULL,
                tenant_id TEXT NOT NULL,
                analyst_id TEXT NOT NULL,
                status TEXT NOT NULL,
                note TEXT,
                created_at DOUBLE PRECISION NOT NULL
            )
            """,
            "CREATE INDEX IF NOT EXISTS idx_reviews_turn ON copilot_turn_reviews (turn_id)",
            "CREATE INDEX IF NOT EXISTS idx_reviews_tenant_time ON copilot_turn_reviews (tenant_id, created_at DESC)",
            """
            CREATE TABLE IF NOT EXISTS knowledge_chunks (
                chunk_id TEXT PRIMARY KEY,
                tenant_id TEXT NOT NULL,
                analyst_id TEXT NOT NULL,
                doc_id TEXT NOT NULL,
                chunk_index INTEGER NOT NULL,
                title TEXT NOT NULL,
                text TEXT NOT NULL,
                embedding_json TEXT,
                embedding_model TEXT,
                created_at DOUBLE PRECISION NOT NULL,
                knowledge_kind TEXT NOT NULL DEFAULT 'memo',
                concept_id TEXT,
                bundle_scope TEXT,
                content_hash TEXT,
                source_uri TEXT,
                authority INTEGER NOT NULL DEFAULT 10
            )
            """,
            "CREATE INDEX IF NOT EXISTS idx_knowledge_scope ON knowledge_chunks (tenant_id, analyst_id, created_at)",
            "CREATE INDEX IF NOT EXISTS idx_knowledge_doc ON knowledge_chunks (tenant_id, analyst_id, doc_id)",
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_knowledge_okf_concept
            ON knowledge_chunks (tenant_id, knowledge_kind, concept_id, chunk_index)
            """,
            """
            CREATE TABLE IF NOT EXISTS batch_blobs (
                job_id TEXT PRIMARY KEY,
                tenant_id TEXT NOT NULL,
                analyst_id TEXT NOT NULL,
                created_at DOUBLE PRECISION NOT NULL,
                payload BYTEA NOT NULL
            )
            """,
            "CREATE INDEX IF NOT EXISTS idx_batch_blobs_created ON batch_blobs (created_at)",
        )
        for stmt in sqls:
            conn.execute(stmt)
        _ensure_postgres_columns(conn)
        conn.commit()
        _pg_schema_ready = True


def _ensure_postgres_columns(conn: StoreConnection) -> None:
    """Additive migrations for older postgres installs."""
    additions = (
        ("agent_runs", "source", "TEXT NOT NULL DEFAULT 'chat'"),
        ("agent_runs", "decision_external_id", "TEXT"),
        ("copilot_turns", "persona", "TEXT"),
        ("copilot_turns", "workflow_id", "TEXT"),
        ("knowledge_chunks", "knowledge_kind", "TEXT NOT NULL DEFAULT 'memo'"),
        ("knowledge_chunks", "concept_id", "TEXT"),
        ("knowledge_chunks", "bundle_scope", "TEXT"),
        ("knowledge_chunks", "content_hash", "TEXT"),
        ("knowledge_chunks", "source_uri", "TEXT"),
        ("knowledge_chunks", "authority", "INTEGER NOT NULL DEFAULT 10"),
    )
    for table, column, typedef in additions:
        cols = {str(r[1]) for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}
        if column not in cols:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {typedef}")


def reset_postgres_schema_flag_for_tests() -> None:
    global _pg_schema_ready
    with _pg_schema_lock:
        _pg_schema_ready = False


def _adapt_insert_or_replace(sql: str) -> str:
    match = _INSERT_OR_REPLACE.search(sql)
    if not match:
        return sql
    table = match.group(1)
    cols = [c.strip() for c in match.group(2).split(",") if c.strip()]
    pk = _UPSERT_PK.get(table.lower())
    if not pk:
        raise StoreMisconfigured(f"INSERT OR REPLACE has no postgres mapping for {table}")
    updates = ", ".join(f"{c}=EXCLUDED.{c}" for c in cols if c.lower() != pk.lower())
    rewritten = _INSERT_OR_REPLACE.sub(f"INSERT INTO {table} ({match.group(2)})", sql, count=1)
    rewritten = rewritten.rstrip().rstrip(";")
    if updates:
        rewritten += f" ON CONFLICT ({pk}) DO UPDATE SET {updates}"
    else:
        rewritten += f" ON CONFLICT ({pk}) DO NOTHING"
    return rewritten


def _qmark_to_percent(sql: str) -> str:
    """Replace ``?`` placeholders; our store SQL does not embed ``?`` in literals."""
    return sql.replace("?", "%s")
