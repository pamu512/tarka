-- Prompt 191: immutable shadow hypothesis evidence on signal-ingest audit rows.
ALTER TABLE audit_logs ADD COLUMN IF NOT EXISTS shadow_matches JSONB;

COMMENT ON COLUMN audit_logs.shadow_matches IS
  'Shadow observation rules that fired on ingest (rule_id, matched, recorded_at) for promotion workflow';
