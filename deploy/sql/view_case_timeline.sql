-- Unified case timeline (Prompt 114): Shadow ``cases``, ``audit_logs`` (signal), ``decisions``.
-- Apply to the orchestrator audit database (same schema as ``tarka_shared.audit_trail`` + ``decisions``).
--
-- Query example:
--   SELECT * FROM public.view_case_timeline
--   WHERE case_id = $1
--   ORDER BY event_at ASC, sort_priority ASC;

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

COMMENT ON VIEW public.view_case_timeline IS
  'Chronological union of ingest signals (audit_logs), policy decisions, and case row creation for one Shadow case id.';
