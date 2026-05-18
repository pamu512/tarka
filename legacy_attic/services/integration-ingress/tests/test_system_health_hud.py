"""Unit tests for system health HUD helpers."""

from integration_ingress.system_health_hud import _ollama_native_base, _probe_host_chip_model


def test_ollama_native_base_strips_v1() -> None:
    assert _ollama_native_base("http://127.0.0.1:11434/v1") == "http://127.0.0.1:11434"


def test_probe_host_chip_model_non_empty() -> None:
    assert _probe_host_chip_model()
