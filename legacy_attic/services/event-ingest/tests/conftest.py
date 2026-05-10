"""Shared fixtures for event-ingest tests."""

import pytest


@pytest.fixture(autouse=True)
def allow_insecure_auth(monkeypatch):
    monkeypatch.setenv("ALLOW_INSECURE_NO_AUTH", "true")
    yield


@pytest.fixture(autouse=True)
def clear_ingest_contract_counters():
    """Isolate contract reject tallies so test order does not leak state."""
    from event_ingest import main

    main._contract_reject_reason_counts.clear()
    yield
