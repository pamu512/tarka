"""
Gate (Prompt 114): ``view_case_timeline`` orders signal → decision → case creation for one ``case_id``.

Requires Postgres + ``psycopg``. Run::

  export VIEW_CASE_TIMELINE_PG_URL="postgresql://USER:PASS@HOST:5432/DB"
  pytest tarka_v2_core/services/shared/tests/test_view_case_timeline_gate.py -q

Or reuse ``IMMUTABLE_CASES_PG_URL`` / ``DATABASE_URL`` (sync ``postgresql://…``).
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[4]
_VIEW_SQL_PATH = _REPO_ROOT / "deploy" / "sql" / "view_case_timeline.sql"


@pytest.fixture
def pg_url() -> str:
    url = (
        os.environ.get("VIEW_CASE_TIMELINE_PG_URL")
        or os.environ.get("IMMUTABLE_CASES_PG_URL")
        or os.environ.get("DATABASE_URL")
        or ""
    ).strip()
    if not url or "postgresql" not in url.lower():
        pytest.skip(
            "Set VIEW_CASE_TIMELINE_PG_URL, IMMUTABLE_CASES_PG_URL, or DATABASE_URL "
            "to a sync Postgres URL for this gate",
        )
    return url.replace("+asyncpg", "").replace("+psycopg", "")


def test_view_case_timeline_orders_signal_decision_case_created(pg_url: str) -> None:
    pytest.importorskip("psycopg")
    import psycopg

    assert _VIEW_SQL_PATH.is_file(), _VIEW_SQL_PATH
    view_sql = _VIEW_SQL_PATH.read_text()

    case_id = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"

    setup_stmts = [
        "DROP VIEW IF EXISTS public.view_case_timeline",
        "DROP TABLE IF EXISTS public.audit_logs CASCADE",
        "DROP TABLE IF EXISTS public.decisions CASCADE",
        "DROP TABLE IF EXISTS public.cases CASCADE",
        """
        CREATE TABLE public.cases (
            id varchar(36) PRIMARY KEY,
            tenant_id varchar(128) NOT NULL DEFAULT 'default',
            name varchar(256) NOT NULL,
            dataset_path varchar(2048),
            is_active boolean NOT NULL DEFAULT false,
            status varchar(32) NOT NULL DEFAULT 'INVESTIGATING',
            assigned_to varchar(128),
            last_optimization_manifest jsonb,
            duckdb_path varchar(2048),
            schema_summary jsonb,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            graph_snapshot jsonb,
            ai_trace text,
            raw_signals_ref uuid
        )
        """,
        """
        CREATE TABLE public.audit_logs (
            id serial PRIMARY KEY,
            case_id varchar(36) NOT NULL REFERENCES public.cases (id) ON DELETE CASCADE,
            action_taken text NOT NULL,
            code_executed text,
            agent_notes text,
            "timestamp" timestamptz NOT NULL DEFAULT now()
        )
        """,
        """
        CREATE TABLE public.decisions (
            id serial PRIMARY KEY,
            entity_id varchar(36) NOT NULL,
            final_decision varchar(64) NOT NULL,
            actions_json jsonb NOT NULL,
            execution_trace_json jsonb NOT NULL,
            blocking_rule_id varchar(64),
            raw_rule_engine_json jsonb NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now()
        )
        """,
        f"""
        INSERT INTO public.cases (id, name, created_at, updated_at)
        VALUES (
            '{case_id}',
            'gate-timeline-case',
            '2026-05-10T18:00:03+00'::timestamptz,
            '2026-05-10T18:00:03+00'::timestamptz
        )
        """,
        f"""
        INSERT INTO public.audit_logs (case_id, action_taken, "timestamp")
        VALUES (
            '{case_id}',
            '{{"source":"gate","kind":"signal"}}',
            '2026-05-10T18:00:00+00'::timestamptz
        )
        """,
        f"""
        INSERT INTO public.decisions (
            entity_id, final_decision, actions_json, execution_trace_json,
            raw_rule_engine_json, created_at
        )
        VALUES (
            '{case_id}',
            'FLAG',
            '[]'::jsonb,
            '[]'::jsonb,
            '{{}}'::jsonb,
            '2026-05-10T18:00:01+00'::timestamptz
        )
        """,
    ]

    with psycopg.connect(pg_url, autocommit=True) as conn:
        for stmt in setup_stmts:
            conn.execute(stmt)
        conn.execute(view_sql)

        cur = conn.execute(
            """
            SELECT event_kind, source_table
            FROM public.view_case_timeline
            WHERE case_id = %s
            ORDER BY event_at ASC, sort_priority ASC
            """,
            (case_id,),
        )
        rows = cur.fetchall()

    assert len(rows) == 3, rows
    assert [r[0] for r in rows] == ["signal", "decision", "case_created"]
    assert [r[1] for r in rows] == ["audit_logs", "decisions", "cases"]
