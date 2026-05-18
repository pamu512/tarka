"""
Gate (Prompt 111): ``triggers/immutable_cases.sql`` rejects ``graph_snapshot`` updates on ``cases``.

Requires Postgres + ``psycopg``. Run::

  export IMMUTABLE_CASES_PG_URL="postgresql://USER:PASS@HOST:5432/DB"
  pytest tarka_v2_core/services/shared/tests/test_immutable_cases_trigger_gate.py -q
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[4]
_TRIGGER_SQL = _REPO_ROOT / "triggers" / "immutable_cases.sql"


@pytest.fixture
def pg_url() -> str:
    url = (os.environ.get("IMMUTABLE_CASES_PG_URL") or os.environ.get("DATABASE_URL") or "").strip()
    if not url or "postgresql" not in url.lower():
        pytest.skip("Set IMMUTABLE_CASES_PG_URL or DATABASE_URL to a sync Postgres URL for this gate")
    return url.replace("+asyncpg", "").replace("+psycopg", "")


def test_graph_snapshot_update_raises_check_violation(pg_url: str) -> None:
    pytest.importorskip("psycopg")
    import psycopg
    from psycopg import errors as pg_errors

    assert _TRIGGER_SQL.is_file(), _TRIGGER_SQL

    ddl = """
    DROP TABLE IF EXISTS public.cases CASCADE;
    CREATE TABLE public.cases (
        id varchar(36) PRIMARY KEY,
        tenant_id varchar(128) NOT NULL DEFAULT 'default',
        name varchar(256) NOT NULL,
        dataset_path varchar(2048),
        is_active boolean NOT NULL DEFAULT false,
        status varchar(32) NOT NULL DEFAULT 'OPEN',
        assigned_to varchar(128),
        last_optimization_manifest jsonb,
        duckdb_path varchar(2048),
        schema_summary jsonb,
        created_at timestamptz NOT NULL DEFAULT now(),
        updated_at timestamptz NOT NULL DEFAULT now(),
        graph_snapshot jsonb,
        ai_trace text,
        raw_signals_ref uuid
    );
    """

    with psycopg.connect(pg_url, autocommit=True) as conn:
        conn.execute(ddl)
        conn.execute(_TRIGGER_SQL.read_text())
        conn.execute(
            """
            INSERT INTO public.cases (id, name, graph_snapshot)
            VALUES ('aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa', 'gate-case', '{"k":0}'::jsonb)
            """
        )

        with pytest.raises(pg_errors.CheckViolation, match="immutable except status and assigned_to"):
            conn.execute(
                """
                UPDATE public.cases
                SET graph_snapshot = '{"mutated":true}'::jsonb
                WHERE id = 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'
                """
            )

        conn.execute(
            """
            UPDATE public.cases
            SET status = 'UNDER_REVIEW', assigned_to = 'analyst-42'
            WHERE id = 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'
            """
        )
        row = conn.execute(
            "SELECT status, assigned_to FROM public.cases WHERE id = 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'"
        ).fetchone()
        assert row is not None
        assert row[0] == "UNDER_REVIEW"
        assert row[1] == "analyst-42"
