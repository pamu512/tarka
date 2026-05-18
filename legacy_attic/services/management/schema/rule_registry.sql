-- Immutable rule version store for forensic replay (PostgreSQL).
-- Application invariant: rule_body and content_hash are never UPDATEd; only valid_to on the
-- previously-active row may be set when a new version is appended.

CREATE TABLE IF NOT EXISTS rule_versions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid (),
    rule_name VARCHAR(255) NOT NULL,
    content_hash CHAR(64) NOT NULL,
    rule_body TEXT NOT NULL,
    valid_from TIMESTAMPTZ NOT NULL,
    valid_to TIMESTAMPTZ NULL,
    CONSTRAINT ck_rule_versions_valid_range CHECK (
        valid_to IS NULL
        OR valid_to > valid_from
    ),
    CONSTRAINT uq_rule_versions_rule_name_content_hash UNIQUE (rule_name, content_hash)
);

COMMENT ON TABLE rule_versions IS 'Append-only rule definitions; each logical update is a new row with a new SHA-256 content hash.';
COMMENT ON COLUMN rule_versions.content_hash IS 'Lowercase hex SHA-256 of UTF-8 rule_body; unique per rule_name.';
COMMENT ON COLUMN rule_versions.valid_from IS 'Inclusive start of validity window (UTC).';
COMMENT ON COLUMN rule_versions.valid_to IS 'Exclusive end of validity window (UTC); NULL means still active.';

-- Fast lookup: which version was active for rule_name at time t:
--   valid_from <= t AND (valid_to IS NULL OR t < valid_to)
CREATE INDEX IF NOT EXISTS ix_rule_versions_name_valid_from ON rule_versions (rule_name, valid_from DESC);

CREATE INDEX IF NOT EXISTS ix_rule_versions_name_active_range ON rule_versions (rule_name, valid_from, valid_to);

-- Optional hardening: forbid mutating immutable columns (PostgreSQL).
CREATE OR REPLACE FUNCTION rule_versions_forbid_immutable_update ()
    RETURNS TRIGGER
    AS $$
BEGIN
    IF TG_OP = 'UPDATE' THEN
        IF NEW.rule_name IS DISTINCT FROM OLD.rule_name
            OR NEW.content_hash IS DISTINCT FROM OLD.content_hash
            OR NEW.rule_body IS DISTINCT FROM OLD.rule_body
            OR NEW.valid_from IS DISTINCT FROM OLD.valid_from
            OR NEW.id IS DISTINCT FROM OLD.id THEN
            RAISE EXCEPTION 'rule_versions row is immutable except valid_to'
                USING ERRCODE = 'integrity_constraint_violation';
        END IF;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS tr_rule_versions_immutable ON rule_versions;

CREATE TRIGGER tr_rule_versions_immutable
    BEFORE UPDATE ON rule_versions
    FOR EACH ROW
    EXECUTE PROCEDURE rule_versions_forbid_immutable_update ();
