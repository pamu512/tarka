"""Semantica bridge stub tests."""

from __future__ import annotations

import os

import pytest


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("SEMANTICA_BRIDGE_ENABLED", "1")
    import semantica_bridge

    semantica_bridge.reset_stub_for_tests()
    # force stub path
    monkeypatch.setattr(semantica_bridge, "_try_real_semantica", False)
    yield
    semantica_bridge.reset_stub_for_tests()


def test_mirror_and_stub_chain():
    from semantica_bridge import mirror_decision, stub_chain

    a = mirror_decision(category="evaluate", scenario="s1", reasoning="r", outcome="review")
    b = mirror_decision(
        category="advise",
        scenario="s2",
        reasoning="r",
        outcome="escalated",
        parent_semantica_id=a.semantica_decision_id,
        relationship="INFLUENCED",
    )
    assert a.ok and b.ok
    chain = stub_chain(b.semantica_decision_id or "")
    assert len(chain["nodes"]) == 2
