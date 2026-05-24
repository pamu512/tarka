-- Operational Signals + normalized ground-truth labels (fast-label feedback loop).
-- PostgreSQL 13+ (uses gen_random_uuid()).
--
-- ``normalized_labels.source_id`` is a polymorphic UUID anchor:
--   * When the label derives from an ingested signal, ``source_id = operational_signals.id``.
--   * When the label derives from case lifecycle / audit history, ``source_id`` stores the
--     stable UUID identifier for that row (application maps ``case_history.id`` / ``audit_logs.id``).
--
-- Do not run this file end-to-end in one shot: it contains both UP and DOWN.
-- Apply UP only (lines between UP and DOWN markers), or run the DOWN block alone to roll back.

-- =============================================================================
-- UP
-- =============================================================================

CREATE TABLE operational_signals (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    idempotency_key VARCHAR(255) NOT NULL,
    target_entity_id VARCHAR(512) NOT NULL,
    signal_type VARCHAR(100) NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT operational_signals_idempotency_key_nonempty CHECK (
        length(trim(idempotency_key)) > 0
    ),
    CONSTRAINT operational_signals_target_entity_id_nonempty CHECK (
        length(trim(target_entity_id)) > 0
    ),
    CONSTRAINT operational_signals_signal_type_nonempty CHECK (
        length(trim(signal_type)) > 0
    )
);

CREATE UNIQUE INDEX idx_operational_signals_idempotency_key
    ON operational_signals
    USING btree (idempotency_key);

CREATE INDEX idx_operational_signals_target_entity_created_at
    ON operational_signals
    USING btree (target_entity_id, created_at DESC);

CREATE INDEX idx_operational_signals_signal_type_created_at
    ON operational_signals
    USING btree (signal_type, created_at DESC);

CREATE INDEX idx_operational_signals_target_entity_signal_type
    ON operational_signals
    USING btree (target_entity_id, signal_type, created_at DESC);

CREATE INDEX idx_operational_signals_metadata_gin
    ON operational_signals
    USING gin (metadata jsonb_path_ops);

CREATE TABLE normalized_labels (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_type VARCHAR(64) NOT NULL,
    source_id UUID NOT NULL,
    entity_id VARCHAR(512) NOT NULL,
    ground_truth_class VARCHAR(32) NOT NULL,
    tags TEXT[] NOT NULL DEFAULT '{}'::text[],
    propagated_to_consortium BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT normalized_labels_source_type_nonempty CHECK (
        length(trim(source_type)) > 0
    ),
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

CREATE INDEX idx_normalized_labels_source_type_created_at
    ON normalized_labels
    USING btree (source_type, created_at DESC);

CREATE INDEX idx_normalized_labels_entity_ground_truth
    ON normalized_labels
    USING btree (entity_id, ground_truth_class, created_at DESC);

CREATE INDEX idx_normalized_labels_source_type_source_id
    ON normalized_labels
    USING btree (source_type, source_id);

CREATE INDEX idx_normalized_labels_propagation_queue
    ON normalized_labels
    USING btree (propagated_to_consortium, created_at DESC)
    WHERE propagated_to_consortium = FALSE;

CREATE INDEX idx_normalized_labels_tags_gin
    ON normalized_labels
    USING gin (tags);

COMMENT ON TABLE operational_signals IS
    'Durable ingress for operational feedback (refunds, analyst dispositions, chargebacks, …).';

COMMENT ON TABLE normalized_labels IS
    'Ground-truth labels normalized from operational signals and case/audit history for training and consortium export.';

COMMENT ON COLUMN normalized_labels.source_type IS
    'Label provenance channel, e.g. ANALYST_DISPOSITION, CHARGEBACK.';

COMMENT ON COLUMN normalized_labels.source_id IS
    'Polymorphic UUID anchor: operational_signals.id or mapped case_history / audit_logs identifier.';

-- =============================================================================
-- DOWN
-- =============================================================================

DROP INDEX IF EXISTS idx_normalized_labels_tags_gin;

DROP INDEX IF EXISTS idx_normalized_labels_propagation_queue;

DROP INDEX IF EXISTS idx_normalized_labels_source_type_source_id;

DROP INDEX IF EXISTS idx_normalized_labels_entity_ground_truth;

DROP INDEX IF EXISTS idx_normalized_labels_source_type_created_at;

DROP INDEX IF EXISTS idx_normalized_labels_ground_truth_created_at;

DROP INDEX IF EXISTS idx_normalized_labels_entity_created_at;

DROP TABLE IF EXISTS normalized_labels;

DROP INDEX IF EXISTS idx_operational_signals_metadata_gin;

DROP INDEX IF EXISTS idx_operational_signals_target_entity_signal_type;

DROP INDEX IF EXISTS idx_operational_signals_signal_type_created_at;

DROP INDEX IF EXISTS idx_operational_signals_target_entity_created_at;

DROP INDEX IF EXISTS idx_operational_signals_idempotency_key;

DROP TABLE IF EXISTS operational_signals;
