"""Environment-driven settings for the management HTTP surface."""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class ManagementSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="TARKA_MANAGEMENT_",
        env_file=".env",
        extra="ignore",
    )

    yaml_rules_root: str = Field(
        default="./rules/yaml",
        description="Directory tree scanned for compiler YAML rule sets (*.yaml / *.yml).",
    )
    lineage_excluded_globs: str = Field(
        default="",
        description="Comma-separated glob patterns (relative to rules root) to exclude.",
    )
    lineage_max_files: int = Field(default=10_000, ge=1, le=500_000)
    lineage_max_file_bytes: int = Field(default=2_000_000, ge=1024, le=50_000_000)
    api_key: str = Field(
        default="",
        description="When non-empty, require matching X-API-Key on lineage endpoints.",
    )


@lru_cache(maxsize=1)
def get_settings() -> ManagementSettings:
    """Cached settings single-flight (tests should call ``get_settings.cache_clear()``)."""
    return ManagementSettings()


def reset_settings_cache() -> None:
    """Clear cached settings (pytest isolation)."""
    get_settings.cache_clear()
