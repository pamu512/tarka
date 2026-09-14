"""D1: silent side-effect doom must be loud at consumer startup."""

from __future__ import annotations

import logging

import pytest

from event_ingest.config import settings
from event_ingest.main import _log_side_effect_auth_config


def test_side_effect_auth_misconfiguration_logs_error_with_remediation(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr(settings, "orchestrator_url", "http://orch.test")
    monkeypatch.setattr(settings, "orchestrator_internal_secret", "")
    with caplog.at_level(logging.ERROR, logger="event-ingest"):
        _log_side_effect_auth_config()
    assert any(
        r.levelno == logging.ERROR and "ORCHESTRATOR_INTERNAL_SECRET" in r.getMessage()
        for r in caplog.records
    )


def test_side_effect_auth_configured_is_quiet(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr(settings, "orchestrator_url", "http://orch.test")
    monkeypatch.setattr(settings, "orchestrator_internal_secret", "s3cret")
    with caplog.at_level(logging.ERROR, logger="event-ingest"):
        _log_side_effect_auth_config()
    assert not [r for r in caplog.records if r.levelno >= logging.ERROR]


def test_side_effect_url_unset_is_quiet(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr(settings, "orchestrator_url", "")
    monkeypatch.setattr(settings, "orchestrator_internal_secret", "")
    with caplog.at_level(logging.ERROR, logger="event-ingest"):
        _log_side_effect_auth_config()
    assert not [r for r in caplog.records if r.levelno >= logging.ERROR]
