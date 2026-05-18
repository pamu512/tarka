"""Unit tests for hardware-first Shadow Copilot tiering (no model loads)."""

from __future__ import annotations

from typing import Any

import pytest

import shadow_copilot as sc


class _VM:
    def __init__(self, total: int, available: int | None = None) -> None:
        self.total = total
        self.available = available if available is not None else total // 2


def _patch_ram_gib(monkeypatch: pytest.MonkeyPatch, total_gib: float) -> None:
    total_bytes = int(total_gib * (1024**3))

    def _vm() -> Any:
        return _VM(total_bytes)

    monkeypatch.setattr(sc.psutil, "virtual_memory", _vm)
    monkeypatch.setattr(sc, "_probe_cuda_vram_gib", lambda: (0, None))
    monkeypatch.setattr(sc, "_mlx_importable", lambda: False)


@pytest.mark.parametrize(
    "total_gib,expect_tier,local_on",
    [
        (6.0, sc.CopilotModelTier.DISABLED, False),
        (10.0, sc.CopilotModelTier.LIGHT, True),
        (32.0, sc.CopilotModelTier.FULL, True),
    ],
)
def test_tier_by_ram_llama_default(
    monkeypatch: pytest.MonkeyPatch,
    total_gib: float,
    expect_tier: sc.CopilotModelTier,
    local_on: bool,
) -> None:
    _patch_ram_gib(monkeypatch, total_gib)
    monkeypatch.setattr(
        sc,
        "fetch_installed_ollama_model_tags",
        lambda url, timeout_sec=2.0: (["phi3:mini", "llama3.2:latest"], None),
    )
    st = sc.evaluate_shadow_copilot_runtime(env_ollama_model="llama3.2:latest")
    assert st.tier == expect_tier
    assert st.local_llm_enabled is local_on
    if expect_tier == sc.CopilotModelTier.DISABLED:
        assert st.requires_cloud_fallback is True
        assert st.effective_ollama_model is None
        assert any(w.code == "CLOUD_FALLBACK_REQUIRED" for w in st.ui_warnings)
    elif expect_tier == sc.CopilotModelTier.LIGHT:
        assert st.effective_ollama_model == "phi3:mini"
        assert st.heavy_models_blocked is True
    else:
        assert st.effective_ollama_model == "llama3.2:latest"


def test_light_tier_keeps_installed_small_user_choice(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_ram_gib(monkeypatch, 12.0)
    monkeypatch.setattr(
        sc,
        "fetch_installed_ollama_model_tags",
        lambda url, timeout_sec=2.0: (["tinyllama:latest", "phi3:mini"], None),
    )
    st = sc.evaluate_shadow_copilot_runtime(env_ollama_model="tinyllama:latest")
    assert st.tier == sc.CopilotModelTier.LIGHT
    assert st.effective_ollama_model == "tinyllama:latest"


def test_shadow_copilot_initialize_and_cloud_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_ram_gib(monkeypatch, 4.0)
    monkeypatch.setattr(
        sc, "fetch_installed_ollama_model_tags", lambda url, timeout_sec=2.0: ([], "down")
    )
    cop = sc.ShadowCopilot(env_ollama_model="llama3.2")
    st = cop.initialize()
    assert st.tier == sc.CopilotModelTier.DISABLED
    with pytest.raises(sc.CloudFallbackRequired):
        cop.assert_local_llm_allowed()


def test_is_heavy_heuristic() -> None:
    assert sc._is_heavy_model_tag("llama3.2:latest") is True
    assert sc._is_heavy_model_tag("phi3:mini") is False
    assert sc._is_heavy_model_tag("qwen2.5:1.5b-instruct") is False
