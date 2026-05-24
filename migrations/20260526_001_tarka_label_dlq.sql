-- Dead-letter queue for malformed label bus payloads (forensic analysis).
-- PostgreSQL 13+ (uses gen_random_uuid()).
--
-- Do not run this file end-to-end in one shot: it contains both UP and DOWN.
-- Apply UP only (lines between UP and DOWN markers), or run the DOWN block alone to roll back.

-- =============================================================================
-- UP
-- =============================================================================

CREATE TABLE tarka_label_dlq (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    normalized_label_id UUID NULL,
    entity_id VARCHAR(512) NULL,
    ground_truth_class VARCHAR(32) NULL,
    rejection_reason TEXT NOT NULL,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    source VARCHAR(64) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT tarka_label_dlq_rejection_reason_nonempty CHECK (
        length(trim(rejection_reason)) > 0
    ),
    CONSTRAINT tarka_label_dlq_source_nonempty CHECK (
        length(trim(source)) > 0
    )
);

CREATE INDEX idx_tarka_label_dlq_normalized_label_id
    ON tarka_label_dlq (normalized_label_id);

CREATE INDEX idx_tarka_label_dlq_entity_created_at
    ON tarka_label_dlq (entity_id, created_at DESC);

CREATE INDEX idx_tarka_label_dlq_source_created_at
    ON tarka_label_dlq (source, created_at DESC);

COMMENT ON TABLE tarka_label_dlq IS
    'Forensic dead-letter queue for label items rejected before JetStream publish.';

-- =============================================================================
-- DOWN
-- =============================================================================

DROP INDEX IF EXISTS idx_tarka_label_dlq_source_created_at;

DROP INDEX IF EXISTS idx_tarka_label_dlq_entity_created_at;

DROP INDEX IF EXISTS idx_tarka_label_dlq_normalized_label_id;

DROP TABLE IF EXISTS tarka_label_dlq;
