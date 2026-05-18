"""Shadow Copilot — hardware-aware local LLM tiering (prevents blind OOM on low-RAM / VDI hosts).

Probes **system RAM** (``psutil``) and optional **CUDA VRAM** / **MLX** presence **before** any model
weights are loaded. Selects an Ollama tag from already-installed models when downgrading; never
pulls weights during this check.
"""

from __future__ import annotations

import json
import logging
import re
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Final, Literal

import psutil
from pydantic import BaseModel, Field

log = logging.getLogger(__name__)

# --- Policy thresholds (GiB, base-1024) --------------------------------------
_RAM_DISABLE_LOCAL_GIB: Final[float] = 8.0
_RAM_FORCE_LIGHT_GIB: Final[float] = 16.0

# Prefer smaller instruct models first (Ollama common tags).
_LIGHT_MODEL_PRIORITY: Final[tuple[str, ...]] = (
    "qwen2.5:1.5b-instruct",
    "qwen2.5:1.5b",
    "qwen2:1.5b-instruct",
    "qwen2:1.5b",
    "phi3:mini",
    "phi3",
    "smollm2:1.7b",
    "gemma2:2b",
    "tinyllama",
)

# Substrings / patterns that imply a heavy default (blocked when RAM < 16 GiB).
_HEAVY_HINTS: Final[tuple[str, ...]] = (
    "70b",
    "72b",
    "65b",
    "40b",
    "34b",
    "32b",
    "30b",
    "27b",
    "22b",
    "14b",
    "13b",
    "12b",
    "9b",
    "8b",
    "llama3.2",
    "llama3.1",
    "llama3:",
    "mixtral",
    "mistral-large",
    "qwen2.5:72b",
    "qwen2.5:32b",
    "qwen2.5:14b",
    "qwen3-vl",
    "qwen3vl",
    "vision",
    "-vl",
)


class CopilotModelTier(StrEnum):
    """Resolved execution tier after the pre-flight hardware probe."""

    FULL = "full"  # env default allowed (RAM >= 16 GiB)
    LIGHT = "light"  # heavy blocked; use small quantized Ollama tag
    DISABLED = "disabled"  # RAM < 8 GiB — no local LLM


class UIWarning(BaseModel):
    """Structured payload for clients (VDI / browser shell) to surface banners."""

    code: str
    severity: Literal["info", "warning", "error"]
    title: str
    detail: str
    action: str | None = None


class HardwareSnapshot(BaseModel):
    """What we detected — logged and echoed to the UI payload."""

    system_ram_total_gib: float = Field(description="psutil.virtual_memory().total / 1024**3")
    system_ram_available_gib: float = Field(
        description="psutil.virtual_memory().available / 1024**3"
    )
    cuda_devices: int = 0
    cuda_total_vram_gib: float | None = None
    mlx_importable: bool = False
    policy_memory_gib: float = Field(
        description="RAM total used for tier policy (VDI-safe: host RAM, not GPU marketing).",
    )


class ShadowCopilotRuntimeStatus(BaseModel):
    """Post-probe status: model choice, tier, and UI-facing warnings."""

    tier: CopilotModelTier
    local_llm_enabled: bool
    requires_cloud_fallback: bool
    effective_ollama_model: str | None = Field(
        default=None,
        description="Ollama model tag to use when local_llm_enabled; None when disabled.",
    )
    env_requested_model: str
    heavy_models_blocked: bool
    hardware: HardwareSnapshot
    installed_ollama_tags_sample: list[str] = Field(default_factory=list)
    selected_because: str
    ui_warnings: list[UIWarning] = Field(default_factory=list)
    ollama_tags_probe_error: str | None = None


class CloudFallbackRequired(RuntimeError):
    """Raised when callers attempt local inference while tier is DISABLED."""

    def __init__(self, status: ShadowCopilotRuntimeStatus) -> None:
        self.status = status
        super().__init__(status.selected_because)


def _bytes_to_gib(n: int | float) -> float:
    return float(n) / (1024.0**3)


def _probe_cuda_vram_gib() -> tuple[int, float | None]:
    """Return (device_count, total_vram_gib or None if not applicable)."""
    try:
        import torch
    except Exception as exc:  # pragma: no cover — optional dep
        log.info("shadow_copilot: torch not available for VRAM probe: %s", exc)
        return 0, None
    try:
        if not torch.cuda.is_available():
            return 0, None
        n = torch.cuda.device_count()
        total = 0
        for i in range(n):
            total += int(torch.cuda.get_device_properties(i).total_memory)
        return n, _bytes_to_gib(total)
    except Exception as exc:
        log.warning("shadow_copilot: CUDA VRAM probe failed: %s", exc)
        return 0, None


def _mlx_importable() -> bool:
    try:
        import mlx.core  # noqa: F401
    except Exception:
        return False
    return True


def probe_hardware_snapshot() -> HardwareSnapshot:
    """Collect RAM and best-effort accelerator memory **without** loading models."""
    vm = psutil.virtual_memory()
    ram_total = _bytes_to_gib(vm.total)
    ram_avail = _bytes_to_gib(vm.available)
    cuda_n, cuda_gib = _probe_cuda_vram_gib()
    mlx_ok = _mlx_importable()
    # VDI posture: tier on **host RAM** so we do not assume 16G+ VRAM that is not there.
    policy = ram_total
    snap = HardwareSnapshot(
        system_ram_total_gib=round(ram_total, 2),
        system_ram_available_gib=round(ram_avail, 2),
        cuda_devices=cuda_n,
        cuda_total_vram_gib=(round(cuda_gib, 2) if cuda_gib is not None else None),
        mlx_importable=mlx_ok,
        policy_memory_gib=round(policy, 2),
    )
    log.info(
        "shadow_copilot hardware probe: ram_total_gib=%.2f ram_avail_gib=%.2f cuda_devices=%d "
        "cuda_vram_gib=%s mlx_importable=%s policy_memory_gib=%.2f (tier uses host RAM)",
        snap.system_ram_total_gib,
        snap.system_ram_available_gib,
        snap.cuda_devices,
        snap.cuda_total_vram_gib,
        snap.mlx_importable,
        snap.policy_memory_gib,
    )
    return snap


def _normalize_model_tag(name: str) -> str:
    return re.sub(r"\s+", "", (name or "").strip().lower())


def _is_heavy_model_tag(tag: str) -> bool:
    t = _normalize_model_tag(tag)
    if not t:
        return False
    return any(hint in t for hint in _HEAVY_HINTS)


def _ollama_native_base(openai_compat_base: str) -> str:
    """Strip trailing /v1 from OpenAI-compatible Ollama URL."""
    u = (openai_compat_base or "").strip().rstrip("/")
    if u.endswith("/v1"):
        return u[:-3]
    return u


def fetch_installed_ollama_model_tags(
    ollama_openai_base_url: str,
    *,
    timeout_sec: float = 2.0,
) -> tuple[list[str], str | None]:
    """GET /api/tags — returns (names, error_message). Does not pull models."""
    native = _ollama_native_base(ollama_openai_base_url)
    if not native.startswith("http"):
        return [], "invalid_ollama_base_url"
    url = native.rstrip("/") + "/api/tags"
    try:
        req = urllib.request.Request(url, method="GET", headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
        data: dict[str, Any] = json.loads(raw)
    except urllib.error.URLError as e:
        return [], str(e.reason if hasattr(e, "reason") else e)
    except json.JSONDecodeError as e:
        return [], f"ollama_tags_json_error: {e}"
    except Exception as e:  # pragma: no cover
        return [], str(e) or "ollama_tags_unknown_error"

    models = data.get("models") or []
    names: list[str] = []
    if isinstance(models, list):
        for m in models:
            if isinstance(m, dict) and m.get("name"):
                names.append(str(m["name"]))
    return sorted(set(names)), None


def _pick_installed_light_model(installed: set[str]) -> str | None:
    for candidate in _LIGHT_MODEL_PRIORITY:
        if candidate in installed:
            return candidate
    # Fuzzy: any installed tag that looks like a small variant
    for tag in sorted(installed):
        tl = _normalize_model_tag(tag)
        if any(
            x in tl for x in ("1.5b", "1.7b", "2b", "mini", "tinyllama", "smollm", "phi3")
        ) and not _is_heavy_model_tag(tag):
            return tag
    return None


def evaluate_shadow_copilot_runtime(
    *,
    env_ollama_model: str,
    ollama_openai_base_url: str = "http://localhost:11434/v1",
) -> ShadowCopilotRuntimeStatus:
    """Pre-flight: probe hardware, query Ollama tags, **then** choose tier and model (no weight load)."""
    requested = (env_ollama_model or "llama3.2").strip() or "llama3.2"
    hw = probe_hardware_snapshot()
    mem = hw.policy_memory_gib
    warnings: list[UIWarning] = []
    installed, tag_err = fetch_installed_ollama_model_tags(ollama_openai_base_url)
    installed_set = set(installed)
    sample = installed[:24]

    # --- < 8 GiB RAM: no local LLM ------------------------------------------------
    if mem < _RAM_DISABLE_LOCAL_GIB:
        reason = (
            f"Host RAM {mem:.2f} GiB is below {_RAM_DISABLE_LOCAL_GIB:.0f} GiB policy floor — "
            "local Shadow Copilot LLM execution is disabled. Use **Cloud Fallback** "
            "(managed API) for this workstation."
        )
        log.warning(
            "shadow_copilot tier=DISABLED: system_ram_total_gib=%.2f cuda_vram_gib=%s — %s",
            hw.system_ram_total_gib,
            hw.cuda_total_vram_gib,
            reason,
        )
        warnings.append(
            UIWarning(
                code="CLOUD_FALLBACK_REQUIRED",
                severity="error",
                title="Local LLM disabled (insufficient memory)",
                detail=reason,
                action="Enable a cloud LLM endpoint in product settings, or use a machine with ≥8 GiB RAM.",
            )
        )
        return ShadowCopilotRuntimeStatus(
            tier=CopilotModelTier.DISABLED,
            local_llm_enabled=False,
            requires_cloud_fallback=True,
            effective_ollama_model=None,
            env_requested_model=requested,
            heavy_models_blocked=True,
            hardware=hw,
            installed_ollama_tags_sample=sample,
            selected_because=reason,
            ui_warnings=warnings,
            ollama_tags_probe_error=tag_err,
        )

    # --- 8–16 GiB: block heavy, prefer light quantized --------------------------
    if mem < _RAM_FORCE_LIGHT_GIB:
        heavy_requested = _is_heavy_model_tag(requested)
        pick = _pick_installed_light_model(installed_set)
        if not heavy_requested and requested in installed_set:
            log.info(
                "shadow_copilot tier=LIGHT: ram_gib=%.2f keeping installed non-heavy model=%r",
                mem,
                requested,
            )
            return ShadowCopilotRuntimeStatus(
                tier=CopilotModelTier.LIGHT,
                local_llm_enabled=True,
                requires_cloud_fallback=False,
                effective_ollama_model=requested,
                env_requested_model=requested,
                heavy_models_blocked=True,
                hardware=hw,
                installed_ollama_tags_sample=sample,
                selected_because=(
                    f"RAM {mem:.2f} GiB < {_RAM_FORCE_LIGHT_GIB:.0f} GiB; configured tag is non-heavy and present in Ollama."
                ),
                ui_warnings=[
                    UIWarning(
                        code="LOCAL_LLM_LIGHT_TIER",
                        severity="info",
                        title="Local model tier: light (low memory)",
                        detail=(
                            f"Host has {mem:.1f} GiB RAM. Large models (e.g. Llama 3.2 8B) stay blocked; "
                            f"current tag `{requested}` is allowed."
                        ),
                        action="Upgrade to ≥16 GiB RAM for full local model freedom.",
                    )
                ],
                ollama_tags_probe_error=tag_err,
            )
        if heavy_requested or pick:
            target = pick or _LIGHT_MODEL_PRIORITY[0]
            if pick is None:
                pull_hint = (
                    f"No small model found in local Ollama. Install one first, e.g. "
                    f"`ollama pull {_LIGHT_MODEL_PRIORITY[0]}` — until then, local chat may fail at runtime."
                )
                log.warning(
                    "shadow_copilot tier=LIGHT: ram_gib=%.2f requested=%r heavy=%s — %s installed_tags=%d",
                    mem,
                    requested,
                    heavy_requested,
                    pull_hint,
                    len(installed_set),
                )
                warnings.append(
                    UIWarning(
                        code="OLLAMA_LIGHT_MODEL_MISSING",
                        severity="warning",
                        title="Small Ollama model not installed",
                        detail=pull_hint,
                        action=f"Run: ollama pull {target}",
                    )
                )
            else:
                log.warning(
                    "shadow_copilot tier=LIGHT: ram_gib=%.2f requested=%r → downgraded_ollama_model=%r "
                    "(heavy models blocked; CUDA devices=%d VRAM_gib=%s MLX=%s)",
                    mem,
                    requested,
                    pick,
                    hw.cuda_devices,
                    hw.cuda_total_vram_gib,
                    hw.mlx_importable,
                )
            warnings.append(
                UIWarning(
                    code="LOCAL_LLM_DOWNGRADED",
                    severity="warning",
                    title="Local model tier: light (low memory)",
                    detail=(
                        f"Detected {mem:.1f} GiB system RAM (< {_RAM_FORCE_LIGHT_GIB:.0f} GiB). "
                        f"Heavy tags like Llama 3.2 8B are blocked; selected `{target}` for Ollama."
                    ),
                    action="Upgrade RAM to ≥16 GiB to unlock larger local models.",
                )
            )
            return ShadowCopilotRuntimeStatus(
                tier=CopilotModelTier.LIGHT,
                local_llm_enabled=True,
                requires_cloud_fallback=False,
                effective_ollama_model=target,
                env_requested_model=requested,
                heavy_models_blocked=True,
                hardware=hw,
                installed_ollama_tags_sample=sample,
                selected_because=(
                    f"RAM {mem:.2f} GiB < {_RAM_FORCE_LIGHT_GIB:.0f} GiB — heavy local models blocked; "
                    f"ollama effective tag `{target}`"
                ),
                ui_warnings=warnings,
                ollama_tags_probe_error=tag_err,
            )
        # Light tier but request already small
        log.info(
            "shadow_copilot tier=LIGHT (no change): ram_gib=%.2f requested=%r already non-heavy",
            mem,
            requested,
        )
        return ShadowCopilotRuntimeStatus(
            tier=CopilotModelTier.LIGHT,
            local_llm_enabled=True,
            requires_cloud_fallback=False,
            effective_ollama_model=requested,
            env_requested_model=requested,
            heavy_models_blocked=True,
            hardware=hw,
            installed_ollama_tags_sample=sample,
            selected_because=f"RAM {mem:.2f} GiB < {_RAM_FORCE_LIGHT_GIB:.0f} GiB but requested tag is already light.",
            ui_warnings=warnings,
            ollama_tags_probe_error=tag_err,
        )

    # --- >= 16 GiB: allow env default --------------------------------------------
    if _is_heavy_model_tag(requested):
        log.info(
            "shadow_copilot tier=FULL: ram_gib=%.2f requested_heavy=%r — allowed (RAM policy satisfied)",
            mem,
            requested,
        )
    else:
        log.info("shadow_copilot tier=FULL: ram_gib=%.2f requested=%r", mem, requested)
    return ShadowCopilotRuntimeStatus(
        tier=CopilotModelTier.FULL,
        local_llm_enabled=True,
        requires_cloud_fallback=False,
        effective_ollama_model=requested,
        env_requested_model=requested,
        heavy_models_blocked=False,
        hardware=hw,
        installed_ollama_tags_sample=sample,
        selected_because=f"RAM {mem:.2f} GiB ≥ {_RAM_FORCE_LIGHT_GIB:.0f} GiB — using configured model `{requested}`.",
        ui_warnings=warnings,
        ollama_tags_probe_error=tag_err,
    )


@dataclass
class ShadowCopilot:
    """Runtime gate: call :meth:`initialize` once at process startup **before** constructing LLM clients."""

    env_ollama_model: str = "llama3.2"
    ollama_openai_base_url: str = "http://localhost:11434/v1"
    status: ShadowCopilotRuntimeStatus | None = None
    _initialized: bool = field(default=False, repr=False)

    def initialize(self) -> ShadowCopilotRuntimeStatus:
        """Hardware + Ollama tag pre-flight (no model weights loaded)."""
        self.status = evaluate_shadow_copilot_runtime(
            env_ollama_model=self.env_ollama_model,
            ollama_openai_base_url=self.ollama_openai_base_url,
        )
        self._initialized = True
        return self.status

    def assert_local_llm_allowed(self) -> None:
        if not self._initialized or self.status is None:
            raise RuntimeError("ShadowCopilot.initialize() must be called first")
        if not self.status.local_llm_enabled:
            raise CloudFallbackRequired(self.status)

    def effective_model(self) -> str:
        """Ollama tag to pass to the OpenAI-compatible client (after :meth:`initialize`)."""
        self.assert_local_llm_allowed()
        assert self.status is not None
        assert self.status.effective_ollama_model is not None
        return self.status.effective_ollama_model

    def ui_status_dict(self) -> dict[str, Any]:
        """JSON-serializable status for API responses."""
        if not self.status:
            return {"initialized": False}
        return {"initialized": True, **self.status.model_dump(mode="json")}


__all__ = [
    "CloudFallbackRequired",
    "CopilotModelTier",
    "HardwareSnapshot",
    "ShadowCopilot",
    "ShadowCopilotRuntimeStatus",
    "UIWarning",
    "evaluate_shadow_copilot_runtime",
    "fetch_installed_ollama_model_tags",
    "probe_hardware_snapshot",
]


def _cli_self_check() -> None:
    """Optional: ``python -m shadow_copilot`` from the package directory for ops."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    model = sys.argv[1] if len(sys.argv) > 1 else "llama3.2"
    st = evaluate_shadow_copilot_runtime(env_ollama_model=model)
    print(json.dumps(st.model_dump(mode="json"), indent=2))


if __name__ == "__main__":
    _cli_self_check()
