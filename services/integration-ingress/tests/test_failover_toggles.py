"""Unit tests for failover toggle state helpers."""

from integration_ingress.failover_toggles import _default_probe_urls


def test_default_probe_urls_non_empty() -> None:
    graph, ai = _default_probe_urls()
    assert graph.startswith("http")
    assert ai.startswith("http")
