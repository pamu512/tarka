-- Prompt 111: enforce immutability on public.cases (evidence locker / Shadow).
--
-- Rules:
--   * UPDATE is allowed to change only ``status`` and ``assigned_to``.
--   * All other columns are immutable after insert (including ``graph_snapshot``, ``ai_trace``,
--     ``raw_signals_ref``, names, paths, manifests, etc.).
--   * ``updated_at`` is bumped automatically on every successful UPDATE (clients must not rely
--     on mutating ``updated_at`` directly).
--
-- Apply after ``cases`` exists and optional evidence-locker columns are present:
--   psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f triggers/immutable_cases.sql
--
-- PostgreSQL 11+ (uses trigger EXECUTE FUNCTION syntax).

ALTER TABLE public.cases
    ADD COLUMN IF NOT EXISTS assigned_to VARCHAR(128);

CREATE OR REPLACE FUNCTION public.trg_cases_immutable_check()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF TG_OP <> 'UPDATE' THEN
        RETURN NEW;
    END IF;

    IF OLD.id IS DISTINCT FROM NEW.id
        OR OLD.tenant_id IS DISTINCT FROM NEW.tenant_id
        OR OLD.name IS DISTINCT FROM NEW.name
        OR OLD.dataset_path IS DISTINCT FROM NEW.dataset_path
        OR OLD.is_active IS DISTINCT FROM NEW.is_active
        OR OLD.last_optimization_manifest IS DISTINCT FROM NEW.last_optimization_manifest
        OR OLD.duckdb_path IS DISTINCT FROM NEW.duckdb_path
        OR OLD.schema_summary IS DISTINCT FROM NEW.schema_summary
        OR OLD.created_at IS DISTINCT FROM NEW.created_at
        OR OLD.graph_snapshot IS DISTINCT FROM NEW.graph_snapshot
        OR OLD.ai_trace IS DISTINCT FROM NEW.ai_trace
        OR OLD.raw_signals_ref IS DISTINCT FROM NEW.raw_signals_ref
    THEN
        RAISE EXCEPTION
            USING MESSAGE = 'cases is immutable except status and assigned_to (violating column change blocked)',
                  ERRCODE = 'check_violation';
    END IF;

    NEW.updated_at := clock_timestamp();
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS cases_immutable_enforce ON public.cases;

CREATE TRIGGER cases_immutable_enforce
    BEFORE UPDATE ON public.cases
    FOR EACH ROW
    EXECUTE PROCEDURE public.trg_cases_immutable_check();

COMMENT ON FUNCTION public.trg_cases_immutable_check() IS
    'Blocks UPDATE on cases columns other than status and assigned_to; refreshes updated_at.';
