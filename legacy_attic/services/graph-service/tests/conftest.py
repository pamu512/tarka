"""Shared fixtures for graph-service tests."""

import os

# graph_service.algorithms imports Neo4j vs Janus implementation at module load time
# (default settings.graph_backend is janusgraph). Unit tests mock Neo4j only.
os.environ.setdefault("GRAPH_BACKEND", "neo4j")

from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.fixture
def mock_neo4j_driver():
    """Create a mocked Neo4j async driver with session support."""
    driver = AsyncMock()
    session = AsyncMock()
    driver.session.return_value.__aenter__ = AsyncMock(return_value=session)
    driver.session.return_value.__aexit__ = AsyncMock(return_value=False)
    return driver, session


@pytest.fixture
def make_neo4j_record():
    """Factory for creating mock Neo4j records."""

    def _make(data: dict):
        record = MagicMock()
        record.__getitem__ = lambda self, key: data[key]
        record.get = lambda key, default=None: data.get(key, default)
        return record

    return _make
