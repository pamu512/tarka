-- Core v2 append-only audit log (matches SQLAlchemy ``AuditLog`` on PostgreSQL).
CREATE TABLE IF NOT EXISTS audit_logs (
    id UUID NOT NULL,
    entity_id UUID NOT NULL,
    raw_payload JSON NOT NULL,
    decision VARCHAR(512) NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
    CONSTRAINT audit_logs_pkey PRIMARY KEY (id)
);

CREATE INDEX IF NOT EXISTS ix_audit_logs_entity_id ON audit_logs (entity_id);

-- Time-window scans (e.g. copilot_batch rolling aggregates) must prune by ``created_at``.
CREATE INDEX IF NOT EXISTS ix_audit_logs_created_at ON audit_logs (created_at);

COMMENT ON TABLE audit_logs IS 'Append-only audit records for Core v2 decisions.';
