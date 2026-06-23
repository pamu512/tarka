"""Optional copilot analytics scheduling."""

import logging

import pytest
from investigation_agent import config, copilot_analytics


@pytest.mark.asyncio
async def test_emit_turn_completed_log_sink(
    caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    caplog.set_level(logging.INFO)
    monkeypatch.setattr(config.settings, "copilot_analytics_enabled", True)
    monkeypatch.setattr(config.settings, "copilot_analytics_sink", "log")
    monkeypatch.setattr(config.settings, "copilot_analytics_hmac_secret", "secret")
    await copilot_analytics._emit(
        config.settings,
        "copilot.turn.completed",
        {
            "ts": "t",
            "tenant_id": "ten",
            "turn_id": "tid",
            "tool_invocation_count": 2,
            "assurance_mode": "standard",
            "had_tool_error": False,
            "assurance_refused": False,
            "analyst_id_hash": "abc",
        },
    )
    assert any("copilot_analytics" in r.message for r in caplog.records)


def test_schedule_turn_completed_noop_when_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config.settings, "copilot_analytics_enabled", False)
    copilot_analytics.schedule_turn_completed(
        config.settings,
        tenant_id="t",
        analyst_id="a",
        turn_id="x",
        tool_invocation_count=0,
        assurance_mode="standard",
        had_tool_error=False,
        assurance_refused=False,
    )


def test_analyst_hash_stable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config.settings, "copilot_analytics_hmac_secret", "k")
    h1 = copilot_analytics._analyst_hash(config.settings, "alice")
    h2 = copilot_analytics._analyst_hash(config.settings, "alice")
    assert h1 == h2
    assert len(h1 or "") == 24
