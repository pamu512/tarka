"""Dialect-specific SQLAlchemy compilation hooks for SQLite migration parity."""

from __future__ import annotations

from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.ext.compiler import compiles


@compiles(JSONB, "sqlite")
def _compile_jsonb_sqlite(_type: JSONB, compiler: object, **kw: object) -> str:
    """PostgreSQL JSONB has no native SQLite equivalent; use JSON affinity (SQLite 3.38+)."""
    return "JSON"


@compiles(PG_UUID, "sqlite")
def _compile_uuid_sqlite(_type: PG_UUID, compiler: object, **kw: object) -> str:
    """Store UUIDs as canonical string form on SQLite (matches Python uuid.UUID round-trip)."""
    return "CHAR(36)"
