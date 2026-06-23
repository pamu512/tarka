"""Gate: deployment profile defaults + env overrides for Redis/graph/JVM hints."""

from __future__ import annotations

import os

import pytest
from pydantic import ValidationError

from tarka_deploy_settings import DeploymentRuntimeSettings


def test_demo_profile_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("REDIS_VELOCITY_TTL", raising=False)
    monkeypatch.delenv("REDIS_VELOCITY_PRUNE_IDLE_SEC", raising=False)
    monkeypatch.delenv("GRAPH_MAX_HOPS", raising=False)
    monkeypatch.setenv("TARKA_DEPLOY_PROFILE", "demo")
    s = DeploymentRuntimeSettings()
    assert s.redis_velocity_ttl_sec == 86_400
    assert s.redis_velocity_prune_idle_sec == 86_400
    assert s.graph_max_hops == 2
    assert s.graph_neighbor_max_hops == 2


def test_cloud_profile_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("REDIS_VELOCITY_TTL", raising=False)
    monkeypatch.delenv("GRAPH_MAX_HOPS", raising=False)
    monkeypatch.setenv("TARKA_DEPLOY_PROFILE", "cloud")
    s = DeploymentRuntimeSettings()
    assert s.redis_velocity_ttl_sec == 2_592_000
    assert s.graph_max_hops == 5


def test_explicit_env_overrides_profile(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TARKA_DEPLOY_PROFILE", "demo")
    monkeypatch.setenv("REDIS_VELOCITY_TTL", "1209600")
    monkeypatch.setenv("GRAPH_MAX_HOPS", "3")
    s = DeploymentRuntimeSettings()
    assert s.redis_velocity_ttl_sec == 1_209_600
    assert s.graph_max_hops == 3


def test_ttl_too_small_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TARKA_DEPLOY_PROFILE", "demo")
    monkeypatch.setenv("REDIS_VELOCITY_TTL", "30")
    with pytest.raises(ValidationError):
        DeploymentRuntimeSettings()


def test_hetu_timeout_defaults_demo_vs_cloud(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in (
        "RULE_ENGINE_GRAPH_FETCH_TIMEOUT_MS",
        "RULE_ENGINE_RUST_FFI_TIMEOUT_MS",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("TARKA_DEPLOY_PROFILE", "demo")
    d = DeploymentRuntimeSettings()
    assert d.rule_engine_graph_fetch_timeout_ms == 50
    assert d.rule_engine_rust_ffi_timeout_ms == 150
    assert d.rule_engine_graph_fetch_timeout_sec == 0.05

    monkeypatch.setenv("TARKA_DEPLOY_PROFILE", "cloud")
    c = DeploymentRuntimeSettings()
    assert c.rule_engine_graph_fetch_timeout_ms == 100
    assert c.rule_engine_rust_ffi_timeout_ms == 50
