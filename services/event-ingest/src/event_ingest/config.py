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

    # E2 DLQ: must sit outside subject_prefix.> or the durable re-consumes the park envelope.
    ingest_dlq_subject: str = "fraud.dlq.evaluate"
    ingest_dlq_stream_name: str = "FRAUD_DLQ"
    ingest_dlq_publish_on_evaluate_4xx: bool = True
    # D1c: after this many deliveries, a persistent side-effect failure parks the
    # message on the DLQ (kind=side_effect_failure) instead of NAK-looping forever.
    ingest_max_deliver: int = 5
    ingest_dlq_publish_on_side_effect_failure: bool = True

    orchestrator_url: str = ""
    orchestrator_internal_secret: str = ""

    # Tenant event-type overlay: consult decision-api GET /v1/event-types when an
    # event_type misses seed ∪ TARKA_EVENT_TYPES (fail-closed on fetch error).
    event_type_overlay_enabled: bool = True
    event_type_overlay_ttl_seconds: float = 30.0


settings = Settings()
