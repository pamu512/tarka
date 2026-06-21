-- Trend agent: triage tickets + Wasm draft rules (PostgreSQL 13+).
-- Apply UP only between markers, or DOWN alone to roll back.

-- =============================================================================
-- UP
-- =============================================================================

CREATE TABLE IF NOT EXISTS trend_triage_tickets (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id VARCHAR(255) NOT NULL,
    entity_id VARCHAR(512) NOT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'OPEN',
    max_z_score DOUBLE PRECISION,
    envelope_json JSONB NOT NULL,
    rag_matrix_json JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT trend_triage_tickets_status_check CHECK (
        status IN ('OPEN', 'ACKNOWLEDGED', 'CLOSED')
    )
);

CREATE INDEX IF NOT EXISTS idx_trend_triage_tickets_tenant_entity_created
    ON trend_triage_tickets (tenant_id, entity_id, created_at DESC);

CREATE TABLE IF NOT EXISTS trend_draft_rules (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id VARCHAR(255) NOT NULL,
    entity_id VARCHAR(512) NOT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'PENDING_VALIDATION',
    rule_package_json JSONB NOT NULL,
    envelope_json JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT trend_draft_rules_status_check CHECK (
        status IN ('PENDING_VALIDATION', 'PROMOTED', 'REJECTED')
    )
);

CREATE INDEX IF NOT EXISTS idx_trend_draft_rules_tenant_status_created
    ON trend_draft_rules (tenant_id, status, created_at DESC);

COMMENT ON TABLE trend_triage_tickets IS
    'Omniscient trend-agent escalations when Z-score exceeds threshold without seasonal/HIL coverage.';

COMMENT ON TABLE trend_draft_rules IS
    'Declarative Wasm rule drafts awaiting analyst promotion from the dashboard.';

-- =============================================================================
-- DOWN
-- =============================================================================

DROP INDEX IF EXISTS idx_trend_draft_rules_tenant_status_created;
DROP TABLE IF EXISTS trend_draft_rules;
DROP INDEX IF EXISTS idx_trend_triage_tickets_tenant_entity_created;
DROP TABLE IF EXISTS trend_triage_tickets;
