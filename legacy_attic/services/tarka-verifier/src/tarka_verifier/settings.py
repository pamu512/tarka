"""Environment configuration for the independent verifier service."""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class VerifierSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="TARKA_VERIFIER_", env_file=".env", extra="ignore")

    verifying_key_hex: str = Field(
        default="",
        description="Hex-encoded 32-byte Ed25519 public key (same semantics as TARKA_VERIFYING_KEY).",
    )
    pagerduty_routing_key: str = Field(
        default="",
        description="PagerDuty Events API v2 routing key (empty = alerts disabled).",
    )
    pagerduty_timeout_seconds: float = Field(default=12.0, ge=2.0, le=120.0)
    bind_host: str = Field(default="127.0.0.1")
    bind_port: int = Field(default=8028, ge=1, le=65535)


@lru_cache(maxsize=1)
def get_settings() -> VerifierSettings:
    return VerifierSettings()


def reset_settings_cache() -> None:
    get_settings.cache_clear()
