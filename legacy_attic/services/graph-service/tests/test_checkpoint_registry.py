"""Checkpoint registry (OSS #49) — no Neo4j required."""

from graph_service.checkpoint_registry import reload_checkpoint_registry, resolve_profile


def test_resolve_default_and_minimal():
    reload_checkpoint_registry()
    p = resolve_profile(None)
    assert p.get("_profile_name") == "standard"
    m = resolve_profile("minimal")
    assert m.get("_profile_name") == "minimal"
    assert float(m.get("risk_score_multiplier", 1)) < 1.0


def test_unknown_falls_back_to_default():
    reload_checkpoint_registry()
    p = resolve_profile("does-not-exist-xyz")
    assert p.get("_profile_name") == "standard"
