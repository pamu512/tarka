"""Guard (#10 setu_prune): dead Setu OSINT NATS wrapper removed.

``nats_lookup.py`` published ``setu.query`` with a reply inbox — zero
responders exist anywhere in the repo (tests faked the reply), so every
production call timed out. Removed with its gate test; the audit lane
(``ai_tool_audit`` → ``ai_tool_logs``) survives and is gated directly.
The Setu lane monitor (``nats_setu_monitor.py`` + analyst UI) reads
audit/finops rows, not the subject — unaffected.
"""

from __future__ import annotations

import importlib

import pytest


def test_nats_lookup_module_removed() -> None:
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("shadow.tools.nats_lookup")


def test_audit_lane_survives() -> None:
    audit = importlib.import_module("shadow.tools.ai_tool_audit")
    assert callable(audit.log_ai_tool_nats_osint)

    models = importlib.import_module("shadow.models.ai_tool_log")
    assert hasattr(models, "AIToolLogORM")


def test_setu_monitor_unaffected() -> None:
    """Monitor keeps its own local subject constant (no nats_lookup import)."""
    import inspect
    import sys
    from pathlib import Path

    _monitor_src = (
        Path(__file__).resolve().parents[2]
        / "integration-ingress"
        / "src"
        / "integration_ingress"
        / "nats_setu_monitor.py"
    ).read_text(encoding="utf-8")
    assert 'SETU_QUERY_SUBJECT = "setu.query"' in _monitor_src
    assert "nats_lookup" not in _monitor_src
