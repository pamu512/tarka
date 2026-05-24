"""Typed orchestrator environment configuration (pydantic-settings)."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

SHADOW_INVESTIGATE_STREAM_NAME = "TARKA_SHADOW_INVESTIGATE"
DEFAULT_SHADOW_INVESTIGATE_SUBJECT = "shadow.investigate"
TARKA_EVENTS_STREAM_NAME = "TARKA_EVENTS"

_DEFAULT_JETSTREAM_MAX_AGE_SEC = 7 * 24 * 3600
_DEFAULT_JETSTREAM_MAX_BYTES = 10 * 1024 * 1024 * 1024


class OrchestratorSettings(BaseSettings):
    """
    Process env + optional ``.env`` / ``deploy/.env``.

    Covers outbox worker timing, NATS JetStream retention, operational-signal ingress
    constraints, and rule shadow-test CI scorecard thresholds.
    """

    model_config = SettingsConfigDict(
        env_file=(".env", "deploy/.env"),
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = Field(
        default="INFO",
        validation_alias="LOG_LEVEL",
    )
    anumana_telemetry_redis_url: str = Field(
        default="",
        validation_alias="ANUMANA_TELEMETRY_REDIS_URL",
    )
    anumana_redis_url: str = Field(
        default="",
        validation_alias="ANUMANA_REDIS_URL",
    )

    # --- Outbox processor ---
    outbox_poll_interval_seconds: float = Field(
        default=2.0,
        ge=0.1,
        validation_alias="OUTBOX_POLL_INTERVAL_SECONDS",
        description="Sleep between outbox drain polls when the queue is empty.",
    )
    outbox_batch_size: int = Field(
        default=100,
        ge=1,
        le=10_000,
        validation_alias="OUTBOX_BATCH_SIZE",
        description="Maximum outbox rows claimed per processor batch.",
    )

    # --- NATS / JetStream ---
    nats_url: str = Field(
        default="",
        validation_alias="NATS_URL",
        description="NATS broker URL for JetStream consumers and shadow dispatch.",
    )
    shadow_dispatch_nats_subject: str = Field(
        default=DEFAULT_SHADOW_INVESTIGATE_SUBJECT,
        min_length=1,
        validation_alias="SHADOW_DISPATCH_NATS_SUBJECT",
    )
    tarka_events_jetstream_max_age_sec: float = Field(
        default=float(_DEFAULT_JETSTREAM_MAX_AGE_SEC),
        gt=0.0,
        validation_alias="TARKA_EVENTS_JETSTREAM_MAX_AGE_SEC",
    )
    tarka_events_jetstream_max_bytes: int = Field(
        default=int(_DEFAULT_JETSTREAM_MAX_BYTES),
        gt=0,
        validation_alias="TARKA_EVENTS_JETSTREAM_MAX_BYTES",
    )
    shadow_investigate_jetstream_stream: str = Field(
        default=SHADOW_INVESTIGATE_STREAM_NAME,
        min_length=1,
        validation_alias="SHADOW_INVESTIGATE_JETSTREAM_STREAM",
    )
    shadow_investigate_jetstream_durable: str = Field(
        default="shadow-investigate-workers",
        min_length=1,
        validation_alias="SHADOW_INVESTIGATE_JETSTREAM_DURABLE",
    )
    shadow_investigate_jetstream_fetch_batch: int = Field(
        default=10,
        ge=1,
        le=100,
        validation_alias="SHADOW_INVESTIGATE_JETSTREAM_FETCH_BATCH",
    )
    shadow_investigate_jetstream_max_age_sec: float = Field(
        default=float(_DEFAULT_JETSTREAM_MAX_AGE_SEC),
        gt=0.0,
        validation_alias="SHADOW_INVESTIGATE_JETSTREAM_MAX_AGE_SEC",
    )
    shadow_investigate_jetstream_max_bytes: int = Field(
        default=int(_DEFAULT_JETSTREAM_MAX_BYTES),
        gt=0,
        validation_alias="SHADOW_INVESTIGATE_JETSTREAM_MAX_BYTES",
    )
    consortium_labels_jetstream_durable: str = Field(
        default="consortium-counter-workers",
        min_length=1,
        validation_alias="CONSORTIUM_LABELS_JETSTREAM_DURABLE",
    )
    consortium_labels_jetstream_fetch_batch: int = Field(
        default=10,
        ge=1,
        le=100,
        validation_alias="CONSORTIUM_LABELS_JETSTREAM_FETCH_BATCH",
    )

    # --- Operational signal ingress constraints ---
    operational_signal_idempotency_ttl_sec: int = Field(
        default=3600,
        ge=1,
        validation_alias="OPERATIONAL_SIGNAL_IDEMPOTENCY_TTL_SEC",
    )
    operational_signal_idempotency_redis_prefix: str = Field(
        default="tarka:operational_signal:idempotency:",
        min_length=1,
        validation_alias="OPERATIONAL_SIGNAL_IDEMPOTENCY_REDIS_PREFIX",
    )
    operational_signal_idempotency_key_max_length: int = Field(
        default=255,
        ge=1,
        le=512,
        validation_alias="OPERATIONAL_SIGNAL_IDEMPOTENCY_KEY_MAX_LENGTH",
    )
    operational_signal_reason_code_max_length: int = Field(
        default=32,
        ge=1,
        le=64,
        validation_alias="OPERATIONAL_SIGNAL_REASON_CODE_MAX_LENGTH",
    )
    operational_signal_operator_id_max_length: int = Field(
        default=128,
        ge=1,
        le=256,
        validation_alias="OPERATIONAL_SIGNAL_OPERATOR_ID_MAX_LENGTH",
    )
    operational_signal_analyst_notes_max_length: int = Field(
        default=4096,
        ge=1,
        le=16_384,
        validation_alias="OPERATIONAL_SIGNAL_ANALYST_NOTES_MAX_LENGTH",
    )

    # --- Rule shadow-test / CI scorecard safety ---
    rule_shadow_test_cohort_limit: int = Field(
        default=1000,
        ge=1,
        le=10_000,
        validation_alias="RULE_SHADOW_TEST_COHORT_LIMIT",
    )
    rule_shadow_test_high_positive_rate_threshold: float = Field(
        default=0.98,
        gt=0.0,
        le=1.0,
        validation_alias="RULE_SHADOW_TEST_HIGH_POSITIVE_RATE_THRESHOLD",
        description="Match rate at or above this value triggers a HIGH POSITIVE RATE warning.",
    )

    @field_validator("log_level", mode="before")
    @classmethod
    def _normalize_log_level(cls, value: object) -> str:
        token = str(value or "INFO").strip().upper()
        allowed = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        if token not in allowed:
            raise ValueError(f"log_level must be one of {sorted(allowed)}, got {token!r}")
        return token

    @field_validator(
        "nats_url",
        "shadow_dispatch_nats_subject",
        "operational_signal_idempotency_redis_prefix",
        "anumana_telemetry_redis_url",
        "anumana_redis_url",
        mode="before",
    )
    @classmethod
    def _strip_strings(cls, value: object) -> object:
        if value is None:
            return value
        if isinstance(value, str):
            return value.strip()
        return value

    def require_nats_url(self, *, purpose: str) -> str:
        url = self.nats_url.strip()
        if not url:
            raise RuntimeError(f"NATS_URL is required for {purpose}")
        return url

    @property
    def resolved_anumana_redis_url(self) -> str:
        return self.anumana_telemetry_redis_url.strip() or self.anumana_redis_url.strip()


@lru_cache(maxsize=1)
def get_settings() -> OrchestratorSettings:
    """Process-wide settings singleton (clear via ``get_settings.cache_clear()`` in tests)."""
    return OrchestratorSettings()


def reset_settings_cache() -> None:
    """Drop cached settings so subsequent ``get_settings()`` re-reads the environment."""
    get_settings.cache_clear()
