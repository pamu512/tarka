"""Shared fixtures for graph-service tests."""

import os

# graph_service.algorithms resolves Neo4j/Janus/AGE implementation at module load.
# Default follows config.py (AGE is the core engine; neo4j/janusgraph are porting
# pads). Tests that exercise a specific backend set GRAPH_BACKEND themselves or
# import the implementation module directly. Never default to janusgraph here:
# importing the Gremlin client leaves a worker thread that blocks interpreter
# exit when no live Gremlin server answered (the full-suite "hang").
os.environ.setdefault("GRAPH_BACKEND", "age")

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
