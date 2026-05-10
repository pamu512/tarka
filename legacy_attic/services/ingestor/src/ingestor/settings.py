"""Environment-backed settings for the ingestor worker and helpers."""

from __future__ import annotations

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from ingestor.descriptor_pin import MANIFEST_DESCRIPTOR_SET_SHA256


class IngestorSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="TARKA_INGESTOR_",
        env_file=".env",
        extra="ignore",
    )

    clickhouse_host: str = Field(default="127.0.0.1", description="ClickHouse HTTP interface host")
    clickhouse_port: int = Field(default=8123, description="ClickHouse HTTP port")
    clickhouse_username: str = Field(default="default")
    clickhouse_password: str = Field(default="")
    clickhouse_database: str = Field(default="tarka_audit")
    clickhouse_secure: bool = Field(default=False)
    clickhouse_connect_timeout_s: float = Field(default=10.0, ge=0.5, le=120.0)
    clickhouse_send_receive_timeout_s: float = Field(default=30.0, ge=1.0, le=600.0)

    #: Logical environment / tenant label persisted on every manifest row and anchor (non-empty).
    tenant_id: str = Field(
        default="default",
        min_length=1,
        max_length=256,
        pattern=r"^[a-zA-Z0-9_.:-]+$",
        description="Tenant identifier for ClickHouse isolation (e.g. env-a, prod-us)",
    )

    redis_dsn: str = Field(
        default="redis://127.0.0.1:6379/2",
        description="Redis for Arq + batch anchoring coordination",
    )
    redis_socket_timeout_s: float = Field(default=10.0, ge=0.5, le=120.0)
    redis_socket_connect_timeout_s: float = Field(default=5.0, ge=0.5, le=120.0)

    batch_size: int = Field(default=1000, ge=1, le=1_000_000)
    redis_batch_list_key: str = Field(default="tarka:ingestor:batch_manifests")
    redis_batch_seq_key: str = Field(default="tarka:ingestor:anchor_batch_seq")
    redis_dlq_key: str = Field(default="tarka:ingestor:manifest_decode_dlq")
    redis_dlq_clickhouse_key: str = Field(
        default="tarka:ingestor:clickhouse_fail_dlq",
        description="Redis fallback list when Postgres DLQ insert fails",
    )
    redis_dlq_schema_key: str = Field(
        default="tarka:ingestor:manifest_schema_dlq",
        description="Redis DLQ for manifests rejected by protobuf schema registry validation",
    )

    manifest_schema_validation_enabled: bool = Field(
        default=True,
        description="Validate EvidenceManifest against registry before ClickHouse",
    )
    expected_manifest_descriptor_sha256: str = Field(
        default="",
        description="Optional SHA-256 (hex) of tarka evidence.proto FileDescriptorProto; mismatch fails startup",
    )

    evidence_table: str = Field(default="evidence_manifests")
    anchors_table: str = Field(default="audit_anchors")

    clickhouse_insert_max_attempts: int = Field(
        default=3,
        ge=1,
        le=20,
        description="Retries per ingest job before parking to failed_evidence",
    )

    postgres_dsn: str = Field(
        default="",
        description="asyncpg DSN for failed_evidence DLQ (postgresql://...)",
    )
    postgres_pool_max_size: int = Field(default=5, ge=1, le=50)
    postgres_command_timeout_s: float = Field(default=60.0, ge=1.0, le=600.0)

    replay_interval_seconds: float = Field(
        default=300.0,
        ge=5.0,
        le=86_400.0,
        description="Background replay worker polling interval",
    )
    replay_batch_size: int = Field(default=50, ge=1, le=5_000)
    replay_abandon_after_attempts: int = Field(
        default=50,
        ge=1,
        le=10_000,
        description="Mark failed_evidence abandoned after this many failed replay tries",
    )

    @field_validator("expected_manifest_descriptor_sha256", mode="before")
    @classmethod
    def _fill_empty_descriptor_pin(cls, v: object) -> object:
        """Treat unset / blank env override as the baked-in digest for this build."""
        if v is None or (isinstance(v, str) and v.strip() == ""):
            return MANIFEST_DESCRIPTOR_SET_SHA256
        return v

    @field_validator("expected_manifest_descriptor_sha256", mode="after")
    @classmethod
    def _normalize_descriptor_pin_hex(cls, v: str) -> str:
        cur = v.strip().lower()
        if len(cur) != 64:
            raise ValueError(
                "expected_manifest_descriptor_sha256 must be exactly 64 hex characters"
            )
        try:
            bytes.fromhex(cur)
        except ValueError as exc:
            raise ValueError(
                "expected_manifest_descriptor_sha256 must be valid hexadecimal"
            ) from exc
        return cur

    @field_validator("tenant_id")
    @classmethod
    def _strip_tenant_id(cls, v: str) -> str:
        s = v.strip()
        if not s:
            raise ValueError("tenant_id must not be empty")
        return s

    arq_max_tries: int = Field(default=5, ge=1, le=50)
