"""Unified timeline view: ``cases``, ``audit_logs``, ``decisions`` (Prompt 114).

Revision ID: 114_view_case_timeline
Revises: 110_cases_assigned_to
Create Date: 2026-05-10

"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection

revision: str = "114_view_case_timeline"
down_revision: Union[str, None] = "110_cases_assigned_to"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _view_ddl() -> str:
    return """
CREATE OR REPLACE VIEW public.view_case_timeline AS
SELECT
  x.case_id,
  x.event_kind,
  x.event_at,
  x.sort_priority,
  x.source_table,
  x.source_id,
  x.detail
FROM (
  SELECT
    c.id AS case_id,
    'signal'::text AS event_kind,
    al."timestamp" AS event_at,
    1 AS sort_priority,
    'audit_logs'::text AS source_table,
    al.id::text AS source_id,
    al.action_taken::text AS detail
  FROM public.cases c
  INNER JOIN public.audit_logs al ON al.case_id = c.id

  UNION ALL

  SELECT
    c.id AS case_id,
    'decision'::text AS event_kind,
    d.created_at AS event_at,
    2 AS sort_priority,
    'decisions'::text AS source_table,
    d.id::text AS source_id,
    d.final_decision::text AS detail
  FROM public.cases c
  INNER JOIN public.decisions d ON d.entity_id = c.id

  UNION ALL

  SELECT
    c.id AS case_id,
    'case_created'::text AS event_kind,
    c.created_at AS event_at,
    3 AS sort_priority,
    'cases'::text AS source_table,
    c.id::text AS source_id,
    c.name::text AS detail
  FROM public.cases c
) x;
"""


def upgrade() -> None:
    bind: Connection = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    insp = inspect(bind)
    names = set(insp.get_table_names(schema="public"))
    need = {"cases", "audit_logs", "decisions"}
    if not need.issubset(names):
        raise RuntimeError(
            "view_case_timeline requires public.cases, public.audit_logs, and public.decisions; "
            f"missing={sorted(need - names)}",
        )
    op.execute(text(_view_ddl()))
    op.execute(
        text(
            "COMMENT ON VIEW public.view_case_timeline IS "
            "'Chronological union of audit signals, decisions, and case creation (Prompt 114).'",
        ),
    )


def downgrade() -> None:
    bind: Connection = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    op.execute(text("DROP VIEW IF EXISTS public.view_case_timeline"))
