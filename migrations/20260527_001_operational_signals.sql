-- Operational signals + normalized ground-truth labels (core DDL).
-- PostgreSQL 13+ (uses gen_random_uuid()).
--
-- Do not run this file end-to-end in one shot: it contains both UP and DOWN.
-- Apply UP only (lines between UP and DOWN markers), or run the DOWN block alone to roll back.

-- =============================================================================
-- UP
-- =============================================================================

CREATE TABLE operational_signals (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    idempotency_key VARCHAR(255) NOT NULL,
    entity_id VARCHAR(512) NOT NULL,
    signal_type VARCHAR(100) NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT operational_signals_idempotency_key_nonempty CHECK (
        length(trim(idempotency_key)) > 0
    ),
    CONSTRAINT operational_signals_entity_id_nonempty CHECK (
        length(trim(entity_id)) > 0
    ),
    CONSTRAINT operational_signals_signal_type_nonempty CHECK (
        length(trim(signal_type)) > 0
    )
);

CREATE UNIQUE INDEX idx_operational_signals_idempotency_key
    ON operational_signals
    USING btree (idempotency_key);

CREATE INDEX idx_operational_signals_entity_created_at
    ON operational_signals
    USING btree (entity_id, created_at DESC);

CREATE INDEX idx_operational_signals_signal_type_created_at
    ON operational_signals
    USING btree (signal_type, created_at DESC);

CREATE INDEX idx_operational_signals_metadata_gin
    ON operational_signals
    USING gin (metadata jsonb_path_ops);

CREATE TABLE normalized_labels (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_id UUID NOT NULL,
    entity_id VARCHAR(512) NOT NULL,
    ground_truth_class VARCHAR(32) NOT NULL,
    tags TEXT[] NOT NULL DEFAULT '{}'::text[],
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT normalized_labels_entity_id_nonempty CHECK (
        length(trim(entity_id)) > 0
    ),
    CONSTRAINT normalized_labels_ground_truth_class_check CHECK (
        ground_truth_class IN ('FRAUD', 'LEGITIMATE')
    )
);

CREATE INDEX idx_normalized_labels_entity_created_at
    ON normalized_labels
    USING btree (entity_id, created_at DESC);

CREATE INDEX idx_normalized_labels_ground_truth_created_at
    ON normalized_labels
    USING btree (ground_truth_class, created_at DESC);

CREATE INDEX idx_normalized_labels_source_id
    ON normalized_labels
    USING btree (source_id);

CREATE INDEX idx_normalized_labels_tags_gin
    ON normalized_labels
    USING gin (tags);

COMMENT ON TABLE operational_signals IS
    'Durable ingress for operational feedback (chargebacks, refunds, analyst overrides).';

COMMENT ON TABLE normalized_labels IS
    'Ground-truth labels normalized from operational signals for training and consortium export.';

COMMENT ON COLUMN normalized_labels.source_id IS
    'UUID anchor to the originating operational signal (``operational_signals.id``).';

-- =============================================================================
-- DOWN
-- =============================================================================

DROP INDEX IF EXISTS idx_normalized_labels_tags_gin;

DROP INDEX IF EXISTS idx_normalized_labels_source_id;

DROP INDEX IF EXISTS idx_normalized_labels_ground_truth_created_at;

DROP INDEX IF EXISTS idx_normalized_labels_entity_created_at;

DROP TABLE IF EXISTS normalized_labels;

DROP INDEX IF EXISTS idx_operational_signals_metadata_gin;

DROP INDEX IF EXISTS idx_operational_signals_signal_type_created_at;

DROP INDEX IF EXISTS idx_operational_signals_entity_created_at;

DROP INDEX IF EXISTS idx_operational_signals_idempotency_key;

DROP TABLE IF EXISTS operational_signals;
