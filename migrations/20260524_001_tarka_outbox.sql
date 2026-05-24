-- Transactional outbox for durable post-ingest side effects (graph, velocity, Shadow tags).
-- PostgreSQL 13+ (uses gen_random_uuid()).
--
-- Do not run this file end-to-end in one shot: it contains both UP and DOWN.
-- Apply UP only (lines between UP and DOWN markers), or run the DOWN block alone to roll back.

-- =============================================================================
-- UP
-- =============================================================================

CREATE TABLE tarka_outbox (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    event_type VARCHAR(100) NOT NULL,
    idempotency_key VARCHAR(255) NOT NULL,
    payload JSONB NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'PENDING',
    retry_count INT NOT NULL DEFAULT 0,
    max_retries INT NOT NULL DEFAULT 5,
    last_error TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    processed_at TIMESTAMPTZ,
    CONSTRAINT tarka_outbox_status_check CHECK (
        status IN ('PENDING', 'PROCESSING', 'COMPLETED', 'FAILED')
    )
);

CREATE UNIQUE INDEX idx_tarka_outbox_idempotency_key
    ON tarka_outbox
    USING btree (idempotency_key);

CREATE INDEX idx_tarka_outbox_status_created_at
    ON tarka_outbox
    USING btree (status, created_at);

-- =============================================================================
-- DOWN
-- =============================================================================

DROP INDEX IF EXISTS idx_tarka_outbox_status_created_at;

DROP INDEX IF EXISTS idx_tarka_outbox_idempotency_key;

DROP TABLE IF EXISTS tarka_outbox;
