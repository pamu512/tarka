"""Gate: orchestrator lifespan boots dependencies without audit poll tasks."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from starlette.testclient import TestClient

_SRC_ORCH = Path(__file__).resolve().parents[1] / "src"
if str(_SRC_ORCH) not in sys.path:
    sys.path.insert(0, str(_SRC_ORCH))


def test_lifespan_skips_background_audit_poll_task() -> None:
    from orchestrator.main import create_app

    app = create_app(
        rule_engine_url="http://rules.test",
        shadow_agent_url=None,
        audit_database_url="sqlite+aiosqlite:///:memory:",
    )
    with TestClient(app) as client:
        assert client.app.state.audit_session_factory is not None
        assert not hasattr(client.app.state, "audit_poll_task")


def test_lifespan_bootstraps_jetstream_when_nats_url_set(monkeypatch: pytest.MonkeyPatch) -> None:
    from orchestrator.main import create_app

    monkeypatch.setenv("NATS_URL", "nats://127.0.0.1:4222")

    mock_js = AsyncMock()
    mock_js.account_info = AsyncMock(return_value=MagicMock())
    mock_js.stream_info = AsyncMock(side_effect=Exception("not found"))
    mock_js.add_stream = AsyncMock()
    mock_js.update_stream = AsyncMock()

    mock_nc = AsyncMock()
    mock_nc.jetstream = MagicMock(return_value=mock_js)
    mock_nc.drain = AsyncMock()
    mock_nc.close = AsyncMock()

    with patch("nats.connect", AsyncMock(return_value=mock_nc)):
        with patch(
            "orchestrator.lifespan.TarkaEventsJetStreamInitializer.ensure_streams_on",
            AsyncMock(),
        ) as ensure_events:
            with patch(
                "orchestrator.lifespan.ensure_shadow_investigate_stream",
                AsyncMock(),
            ) as ensure_shadow:
                app = create_app(rule_engine_url="http://rules.test", shadow_agent_url=None)
                with TestClient(app) as client:
                    assert client.app.state.shadow_dispatch_nats is mock_nc
                    assert client.app.state.shadow_dispatch_jetstream is mock_js

    ensure_events.assert_awaited_once()
    ensure_shadow.assert_awaited_once()
