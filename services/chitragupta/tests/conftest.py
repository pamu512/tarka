import os

import pytest

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")


@pytest.fixture(autouse=True)
def _reset_plugin_registry():
    from chitragupta import plugin_sdk as ps

    ps._REGISTRY.clear()
    yield
    ps._REGISTRY.clear()
