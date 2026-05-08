-- Dead-letter queue for EvidenceManifest rows that failed ClickHouse ingest after retries.
-- Apply against the ingestor Postgres database (same or separate from core API DB).

CREATE TABLE IF NOT EXISTS failed_evidence (
    id BIGSERIAL PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    raw_manifest BYTEA NOT NULL,
    manifest_b64 TEXT,
    last_error TEXT NOT NULL,
    failure_phase TEXT NOT NULL DEFAULT 'clickhouse_insert',
    replay_attempts INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'replayed', 'abandoned')),
    replayed_at TIMESTAMPTZ,
    last_replay_error TEXT
);

CREATE INDEX IF NOT EXISTS idx_failed_evidence_pending_created
    ON failed_evidence (status, created_at)
    WHERE status = 'pending';

COMMENT ON TABLE failed_evidence IS 'DLQ for EvidenceManifest protobuf bytes when ClickHouse sink exhausted retries';
