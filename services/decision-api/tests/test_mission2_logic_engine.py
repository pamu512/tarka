"""Mission 2: rule compiler and gitops contract checks."""

import pytest
from httpx import ASGITransport, AsyncClient

from decision_api.main import app


@pytest.fixture
async def asgi_client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
