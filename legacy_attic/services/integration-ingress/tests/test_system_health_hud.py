"""Unit tests for system health HUD helpers (Prompt 169)."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

from integration_ingress import system_health_hud as _mod


def test_ollama_native_base_strips_v1_suffix() -> None:
    assert _mod._ollama_native_base("http://127.0.0.1:11434/v1") == "http://127.0.0.1:11434"
    assert _mod._ollama_native_base("http://127.0.0.1:11434/") == "http://127.0.0.1:11434"


def test_probe_host_chip_model_non_empty() -> None:
    assert _mod._probe_host_chip_model()


def test_build_system_health_hud_payload() -> None:
    http = MagicMock()
    tags = MagicMock()
    tags.status_code = 200
    ps = MagicMock()
    ps.status_code = 200
    ps.json.return_value = {"models": [{"name": "llama3"}], "pending": 2}
    http.get = AsyncMock(side_effect=[tags, ps])

    redis = MagicMock()
    redis.ping = AsyncMock()

    payload = asyncio.run(
        _mod.build_system_health_hud_payload(
            http=http,
            redis_client=redis,
            redis_url="redis://127.0.0.1:6379/0",
            ollama_base_url="http://127.0.0.1:11434/v1",
        ),
    )
    assert payload["source"] == "live"
    assert payload["redis"]["reachable"] is True
    assert payload["ollama"]["reachable"] is True
    assert payload["ollama"]["queue_depth"] == 2
