"""Gate: legacy ``POST /v1/ai/feedback`` bridges to operational-signals (JSONL sink removed)."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from starlette.testclient import TestClient

_SRC_ORCH = Path(__file__).resolve().parents[1] / "src"
_SRC_INGESTOR = Path(__file__).resolve().parents[2] / "ingestor" / "src"
for _p in (_SRC_ORCH, _SRC_INGESTOR):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from main import create_app  # noqa: E402


def test_post_ai_feedback_bridges_to_operational_signals(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ORCHESTRATOR_V1_RATE_LIMIT_RPM", "0")
    import models.operational_signals  # noqa: F401, PLC0415

    redis = AsyncMock()
    redis.set = AsyncMock(return_value=True)
    redis.delete = AsyncMock(return_value=1)
    redis.ping = AsyncMock(return_value=True)

    app = create_app(
        rule_engine_url="http://rules.test",
        shadow_agent_url=None,
        audit_database_url="sqlite+aiosqlite:///:memory:",
        anumana_redis_client=redis,
    )
    payload = {
        "rejection_reasons": ["Hallucinated merchant name", "Contradicts ledger"],
        "tenant_id": "demo",
        "trace_id": "tr-gate-001",
        "source": "pytest",
        "context": "Analyst rejected Shadow narrative.",
    }
    with TestClient(app) as client:
        r = client.post("/v1/ai/feedback", json=payload)
    assert r.status_code == 202, r.text
    body = r.json()
    assert body["ok"] is True
    assert body["deprecated"] is True
    assert body["event_id"] == body["feedback_id"]
    assert r.headers.get("Deprecation") == "true"


def test_post_ai_feedback_requires_at_least_one_reason() -> None:
    app = create_app(
        rule_engine_url="http://rules.test",
        shadow_agent_url=None,
    )
    with TestClient(app) as client:
        r = client.post("/v1/ai/feedback", json={"rejection_reasons": []})
    assert r.status_code == 422
