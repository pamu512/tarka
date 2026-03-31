"""Shared fixtures for graph-service tests."""
import pytest
from unittest.mock import AsyncMock, MagicMock


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
