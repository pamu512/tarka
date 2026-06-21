-- Unified signal ingest: HMAC-SHA256 over canonical JSON (SYSTEM_SECRET).
ALTER TABLE audit_logs ADD COLUMN IF NOT EXISTS integrity_signature VARCHAR(128);

COMMENT ON COLUMN audit_logs.integrity_signature IS 'HMAC-SHA256 hex over canonical unified signal JSON using SYSTEM_SECRET';
