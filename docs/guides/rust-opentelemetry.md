# OpenTelemetry for Rust services (`event-ingest`, `analytics-sink`)

## Recommended wiring

1. Add OTLP exporter crates (`opentelemetry`, `opentelemetry_sdk`, `opentelemetry-otlp`, `tracing-opentelemetry`)
   aligned on a single minor release train.
2. Initialize a `SdkTracerProvider` in `main` **before** `tracing_subscriber::fmt::init()` when
   `OTEL_EXPORTER_OTLP_ENDPOINT` is set.
3. Propagate `traceparent` on NATS payloads (JSON field) alongside `trace_id` so Python services
   can continue spans started in Rust.

## HTTP ingress

Axum `TraceLayer` + `tower_http::trace` can attach request spans; export via OTLP HTTP/gRPC to your
collector. Keep cardinality bounded (avoid raw `entity_id` as span attributes in high-QPS paths).
