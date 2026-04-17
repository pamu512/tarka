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
    # Optional: enable single-event idempotency for POST /v1/events (header or metadata).
    redis_url: str = ""
    idempotency_ttl_seconds: int = 86400
    idempotency_key_prefix: str = "ingest:idemp"
    # E1: optional | required envelope { schema_version: "1", event: { ... } }
    ingest_envelope_mode: str = "optional"
    # When true, POST /v1/events requires Idempotency-Key (or metadata.idempotency_key).
    ingest_require_idempotency_key: bool = False
    # E2: publish poison / rule-reject evaluate outcomes to a DLQ subject (same stream wildcard fraud.events.>).
    ingest_dlq_subject: str = ""
    ingest_dlq_publish_on_evaluate_4xx: bool = False


settings = Settings()
