"""Lightweight SQLAlchemy ``Base`` for shared ORM models (no engine coupling)."""

from .session import Base

__all__ = ["Base"]
