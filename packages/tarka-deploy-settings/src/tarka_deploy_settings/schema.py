"""
Enterprise deployments retain **graph** history in Neo4j / warehouse stores for AML (90+ days).
Redis velocity keys are **operational aggregates**; TTLs and prune windows belong in validated env
config—not fixed 24-hour assumptions in scripts.
"""

from __future__ import annotations

from typing import Literal

from pydantic import AliasChoices, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class DeploymentRuntimeSettings(BaseSettings):
    """Process env + optional ``.env`` / ``deploy/.env`` relative to the current working directory."""

    model_config = SettingsConfigDict(
        env_file=(".env", "deploy/.env"),
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    tarka_deploy_profile: Literal["demo", "cloud"] = Field(
        default="demo",
        validation_alias=AliasChoices("TARKA_DEPLOY_PROFILE", "DEPLOY_PROFILE"),
        description="demo=laptop defaults; cloud=higher Redis TTL + deeper graph traversals",
    )

    redis_velocity_ttl_sec: int | None = Field(
        default=None,
        validation_alias="REDIS_VELOCITY_TTL",
        description="Canonical TTL (seconds) for velocity aggregate keys / baseline for prune scripts.",
    )

    redis_velocity_prune_idle_sec: int | None = Field(
        default=None,
        validation_alias="REDIS_VELOCITY_PRUNE_IDLE_SEC",
        description="Prune script deletes velocity keys with OBJECT IDLETIME ≥ this many seconds.",
    )

    graph_max_hops: int | None = Field(
        default=None,
        validation_alias="GRAPH_MAX_HOPS",
        description="Undirected neighbor expansion depth for graph probes.",
    )

    redis_cache_max_entries: int | None = Field(
        default=None,
        validation_alias="REDIS_CACHE_MAX_ENTRIES",
        description="Optional cap for Redis-backed caches (service-specific consumers).",
    )

    neo4j_jvm_heap_max_mb: int | None = Field(
        default=None,
        validation_alias=AliasChoices("NEO4J_JVM_HEAP_MAX_MB", "NEO4J_HEAP_MB"),
        description="Compose hint: map to NEO4J_server_memory_heap_max__size (e.g. 4g).",
    )

    janusgraph_jvm_heap_max_mb: int | None = Field(
        default=None,
        validation_alias=AliasChoices("JANUSGRAPH_JVM_HEAP_MAX_MB", "JANUSGRAPH_HEAP_MB"),
        description="Compose hint for JanusGraph / Gremlin Server JVM heap.",
    )

    cassandra_jvm_heap_max_mb: int | None = Field(
        default=None,
        validation_alias="CASSANDRA_JVM_HEAP_MAX_MB",
        description="Compose hint for Cassandra JVM heap (Janus+Cassandra demos).",
    )

    rule_engine_graph_fetch_timeout_ms: int | None = Field(
        default=None,
        validation_alias="RULE_ENGINE_GRAPH_FETCH_TIMEOUT_MS",
        description="Neo4j/Janus graph context probe budget for Hetu rule-engine (async); 0 disables.",
    )

    rule_engine_rust_ffi_timeout_ms: int | None = Field(
        default=None,
        validation_alias="RULE_ENGINE_RUST_FFI_TIMEOUT_MS",
        description="Wall-clock ceiling for Python→Rust Hetu FFI calls; 0 disables.",
    )

    @field_validator(
        "redis_velocity_ttl_sec",
        "redis_velocity_prune_idle_sec",
        "graph_max_hops",
        "rule_engine_graph_fetch_timeout_ms",
        "rule_engine_rust_ffi_timeout_ms",
        mode="before",
    )
    @classmethod
    def _empty_str_none(cls, v: object) -> object:
        if v == "":
            return None
        return v

    @model_validator(mode="after")
    def _defaults_and_validate(self) -> DeploymentRuntimeSettings:
        demo_ttl = 86_400
        cloud_ttl = 2_592_000  # 30 days

        if self.redis_velocity_ttl_sec is None:
            self.redis_velocity_ttl_sec = demo_ttl if self.tarka_deploy_profile == "demo" else cloud_ttl

        if self.graph_max_hops is None:
            self.graph_max_hops = 2 if self.tarka_deploy_profile == "demo" else 5

        if self.redis_velocity_prune_idle_sec is None:
            self.redis_velocity_prune_idle_sec = self.redis_velocity_ttl_sec

        if self.rule_engine_graph_fetch_timeout_ms is None:
            # Demo: tolerate local Janus cache; cloud: fail-open before checkout SLA burns.
            self.rule_engine_graph_fetch_timeout_ms = 50 if self.tarka_deploy_profile == "demo" else 100

        if self.rule_engine_rust_ffi_timeout_ms is None:
            self.rule_engine_rust_ffi_timeout_ms = 150 if self.tarka_deploy_profile == "demo" else 50

        self._check_ttl("redis_velocity_ttl_sec", self.redis_velocity_ttl_sec)
        self._check_ttl("redis_velocity_prune_idle_sec", self.redis_velocity_prune_idle_sec)

        g = int(self.graph_max_hops)
        if g < 1 or g > 16:
            msg = "graph_max_hops must be between 1 and 16"
            raise ValueError(msg)

        if self.redis_cache_max_entries is not None and self.redis_cache_max_entries < 1:
            msg = "redis_cache_max_entries must be >= 1 when set"
            raise ValueError(msg)

        for name in ("neo4j_jvm_heap_max_mb", "janusgraph_jvm_heap_max_mb", "cassandra_jvm_heap_max_mb"):
            v = getattr(self, name)
            if v is not None and v < 128:
                msg = f"{name} must be >= 128 when set"
                raise ValueError(msg)

        for name in ("rule_engine_graph_fetch_timeout_ms", "rule_engine_rust_ffi_timeout_ms"):
            v = getattr(self, name)
            if v < 0:
                msg = f"{name} must be >= 0 (0 = disable timeout)"
                raise ValueError(msg)
            if v > 0 and v > 600_000:
                msg = f"{name} must be <= 600000 ms when non-zero"
                raise ValueError(msg)

        return self

    @staticmethod
    def _check_ttl(field: str, seconds: int) -> None:
        if seconds < 60:
            msg = f"{field} must be >= 60 (use explicit CLI overrides in tests for smaller windows)"
            raise ValueError(msg)
        if seconds > 31_536_000:
            msg = f"{field} must be <= 365 days"
            raise ValueError(msg)

    @property
    def graph_neighbor_max_hops(self) -> int:
        """Clamped hop depth for graph service clients (1–16)."""
        g = int(self.graph_max_hops or 2)
        return max(1, min(g, 16))

    @property
    def rule_engine_graph_fetch_timeout_sec(self) -> float | None:
        """Seconds for ``asyncio.wait_for`` around graph context probes; ``None`` if disabled."""
        ms = int(self.rule_engine_graph_fetch_timeout_ms or 0)
        if ms <= 0:
            return None
        return ms / 1000.0

    @property
    def rule_engine_rust_ffi_timeout_sec(self) -> float | None:
        """Seconds for ThreadPoolExecutor-backed Rust FFI calls; ``None`` if disabled."""
        ms = int(self.rule_engine_rust_ffi_timeout_ms or 0)
        if ms <= 0:
            return None
        return ms / 1000.0
