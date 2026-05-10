"""Shared SQLAlchemy declarative base for audit-plane models used across services."""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Single registry so Alembic and apps see one metadata graph."""
