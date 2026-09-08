#!/usr/bin/env python3
"""Expand/contract: UP must not silent-destroy durable tables."""

from __future__ import annotations

import unittest
from pathlib import Path

from schema_migration_policy import (
    DURABLE,
    alembic_upgrade_drops,
    forbidden_up_drops,
    scan_repo_migrations,
    up_sql,
)

_REPO = Path(__file__).resolve().parents[3]


class TestSchemaMigrationPolicy(unittest.TestCase):
    def test_up_add_column_is_expand(self) -> None:
        sql = """
-- =============================================================================
-- UP
-- =============================================================================
ALTER TABLE audit_logs ADD COLUMN IF NOT EXISTS integrity_signature VARCHAR(128);
-- =============================================================================
-- DOWN
-- =============================================================================
ALTER TABLE audit_logs DROP COLUMN IF EXISTS integrity_signature;
"""
        self.assertEqual(forbidden_up_drops(sql), [])
        self.assertIn("ADD COLUMN", up_sql(sql))
        self.assertNotIn("DROP COLUMN", up_sql(sql))

    def test_up_drop_audit_logs_is_silent_destroy(self) -> None:
        sql = """
-- UP
DROP TABLE IF EXISTS audit_logs;
-- DOWN
CREATE TABLE audit_logs (id int);
"""
        self.assertIn("audit_logs", forbidden_up_drops(sql))

    def test_down_drop_is_allowed(self) -> None:
        sql = """
-- =============================================================================
-- UP
-- =============================================================================
CREATE TABLE tarka_outbox (id uuid);
-- =============================================================================
-- DOWN
-- =============================================================================
DROP TABLE IF EXISTS tarka_outbox;
"""
        self.assertEqual(forbidden_up_drops(sql), [])

    def test_alter_drop_column_targets_table_not_column(self) -> None:
        sql = """
-- UP
ALTER TABLE audit_logs DROP COLUMN IF EXISTS integrity_signature;
-- DOWN
ALTER TABLE audit_logs ADD COLUMN integrity_signature VARCHAR(128);
"""
        self.assertIn("audit_logs", forbidden_up_drops(sql))

    def test_truncate_table_keyword_is_not_the_name(self) -> None:
        sql = "-- UP\nTRUNCATE TABLE decision_audit;\n-- DOWN\n"
        self.assertIn("decision_audit", forbidden_up_drops(sql))

    def test_alembic_upgrade_drop_table_is_forbidden(self) -> None:
        py = """
def upgrade() -> None:
    op.drop_table("decision_audit")

def downgrade() -> None:
    pass
"""
        self.assertIn("decision_audit", alembic_upgrade_drops(py))

    def test_alembic_downgrade_drop_is_allowed(self) -> None:
        py = """
def upgrade() -> None:
    op.create_table("decision_audit")

def downgrade() -> None:
    op.drop_table("decision_audit")
    op.drop_column("investigation_cases", "claimed_by")
"""
        self.assertEqual(alembic_upgrade_drops(py), [])

    def test_repo_up_sections_do_not_drop_durable(self) -> None:
        errors = scan_repo_migrations(_REPO)
        self.assertEqual(errors, [], msg="\n".join(errors))
        self.assertTrue(DURABLE)


if __name__ == "__main__":
    raise SystemExit(unittest.main())
