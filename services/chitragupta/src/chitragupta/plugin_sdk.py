from __future__ import annotations
from typing import Any

from pydantic import BaseModel, Field

from chitragupta.config import settings
from chitragupta.contract_compat import assert_contract_compatible

"""Plugin registration, discovery, and manifest contract (issue #62)."""

class PluginManifest(BaseModel):
    plugin_id: str = Field(min_length=2, max_length=128, pattern=r"^[a-z0-9][a-z0-9_.-]*$")
    contract_version: str = Field(default="1.0.0", description="Semantic contract version for this plugin surface.")
    display_name: str = ""
    capabilities: dict[str, str] = Field(default_factory=dict)
    emitter_targets_supported: list[str] = Field(default_factory=list)


_REGISTRY: dict[str, PluginManifest] = {}


def register_plugin(manifest: PluginManifest) -> PluginManifest:
    assert_contract_compatible(
        plugin_contract=manifest.contract_version,
        server_contract=settings.server_contract_version,
    )
    _REGISTRY[manifest.plugin_id] = manifest
    return manifest


def get_plugin(plugin_id: str) -> PluginManifest | None:
    return _REGISTRY.get(plugin_id)


def list_plugins() -> list[dict[str, Any]]:
    return [m.model_dump(mode="json") for m in _REGISTRY.values()]


def seed_builtin_plugins() -> None:
    """Register built-in demo plugins (deterministic capability matrix for tests)."""
    if "scorecard.json" in _REGISTRY:
        return
    register_plugin(
        PluginManifest(
            plugin_id="scorecard.json",
            contract_version=settings.server_contract_version,
            display_name="JSON scorecard adapter",
            capabilities={"input": "tabular", "output": "json_scorecard", "multi_tenant": "true"},
            emitter_targets_supported=["json", "csv"],
        ),
    )
    register_plugin(
        PluginManifest(
            plugin_id="bi.export",
            contract_version=settings.server_contract_version,
            display_name="BI export adapter",
            capabilities={"input": "tabular", "output": "warehouse_slice", "multi_tenant": "true"},
            emitter_targets_supported=["json", "csv"],
        ),
    )
