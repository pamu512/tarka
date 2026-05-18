from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    nats_url: str = "nats://localhost:4222"
    decision_api_url: str = "http://localhost:8000"
    stream_name: str = "FRAUD_EVENTS"
    subject_prefix: str = "fraud.events"
    batch_flush_ms: int = 100
    max_batch_size: int = 256
    api_keys: str = ""
    upstream_api_key: str = ""
    # Optional: enable single-event idempotency for POST /v1/events (header or metadata).
    redis_url: str = ""
    idempotency_ttl_seconds: int = 86400
    idempotency_key_prefix: str = "ingest:idemp"
    # E1 contract-first: optional | required — required = only `{schema_version:"1", event:{...}}`
    ingest_envelope_mode: str = "optional"
    # R3.1 — reject ingest when Idempotency-Key missing (set INGEST_REQUIRE_IDEMPOTENCY_KEY=true)
    ingest_require_idempotency_key: bool = False

    # E2 DLQ: publish poison / bad-evaluate payloads to JetStream (same stream wildcard fraud.events.>)
    ingest_dlq_subject: str = "fraud.events.dlq"
    ingest_dlq_publish_on_evaluate_4xx: bool = False


settings = Settings()
