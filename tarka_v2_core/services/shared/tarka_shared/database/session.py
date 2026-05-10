"""Declarative base only — engines live in service-specific modules."""

from __future__ import annotations

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Shared metadata registry for ``tarka_shared`` ORM models."""
