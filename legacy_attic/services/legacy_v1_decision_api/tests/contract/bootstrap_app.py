"""Process-wide patched Decision API app for Schemathesis module-level schema binding.

`schemathesis.openapi.parametrize` must decorate tests at import time, so the FastAPI `app`
and `openapi.from_asgi(...)` schema are built here once per worker (before collection).
"""

from __future__ import annotations

import os
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

_PATCHERS: list = []
_STARTED = False

# Shared with Schemathesis + binary fuzz tests so RBAC-protected routes authenticate consistently.
CONTRACT_API_KEY = "schemathesis-contract-key"


def ensure_patched_app():
    """Apply long-lived patches and return the FastAPI application singleton."""
    global _STARTED
    os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///")
    os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
    os.environ["API_KEYS"] = CONTRACT_API_KEY
    os.environ.setdefault("SERVICE_API_KEY_ROLE", "admin")
    os.environ.setdefault("SCHEMATHESIS_PHASE", "contract")
    # Property tests issue many requests; in-memory limiter would return 429 and hide real failures.
    os.environ.setdefault("RATE_LIMIT_RPM", "1000000")
    os.environ.setdefault("ALLOW_INSECURE_NO_AUTH", "true")

    if not _STARTED:
        redis_mock = MagicMock()
        redis_mock.connect = AsyncMock()
        redis_mock.close = AsyncMock()
        redis_client = AsyncMock()
        redis_client.ping = AsyncMock(return_value=True)
        redis_mock._client = redis_client
        redis_mock.is_tag_store_available = False
        redis_mock.get_tags = AsyncMock(return_value=[])
        redis_mock.merge_tags = AsyncMock(return_value=[])
        redis_mock.set_cached_score = AsyncMock()
        redis_mock.store_nonce = AsyncMock()
        redis_mock.consume_nonce = AsyncMock(return_value=True)
        redis_mock.check_and_store_replay_signature = AsyncMock(return_value=False)

        mock_agg = MagicMock()
        mock_agg._client = None

        def _ingest_stats_ok() -> dict[str, Any]:
            # ``capacity==0`` skips buffer pressure in ``health_deep._ingest_buffer_check``.
            return {
                "capacity": 0,
                "in_flight": 0,
                "accepting_new_requests": True,
                "buffer_pressure_percent": 80,
            }

        # Do **not** mock ``init_db``: lifespan must run real SQLite ``create_all`` so contract
        # traffic against ``/v1/decisions/evaluate`` and audit paths never hits missing tables.
        _PATCHERS.extend(
            [
                patch("decision_api.redis_store.redis_tags", redis_mock),
                patch("decision_api.main.redis_tags", redis_mock),
                # Other modules bind ``redis_tags`` at import time before the store patch wins.
                patch("decision_api.health_deep.redis_tags", redis_mock),
                patch("decision_api.main.load_rules"),
                patch("decision_api.main.agg_store", mock_agg),
                patch("decision_api.health_deep.tarka_ingest_stats", _ingest_stats_ok),
            ]
        )

        for p in _PATCHERS:
            p.start()
        _STARTED = True

    from decision_api.main import app

    return app
