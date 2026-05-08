//! OpenTelemetry trace export for `tracing` spans (OTLP over **gRPC / tonic** to a collector).
//!
//! Call [`init_tracer`] once at process startup (inside a Tokio runtime). Use [`shutdown_tracer`]
//! on graceful shutdown to flush pending spans.

use std::sync::Mutex;
use std::time::Duration;

use opentelemetry::global;
use opentelemetry::trace::noop::NoopTracerProvider;
use opentelemetry_otlp::{ExporterBuildError, SpanExporter, WithExportConfig};
use opentelemetry_sdk::trace::SdkTracerProvider;
use opentelemetry_sdk::Resource;
use thiserror::Error;
use tokio::runtime::Handle;
use tracing_subscriber::layer::SubscriberExt;
use tracing_subscriber::util::SubscriberInitExt;
use tracing_subscriber::{EnvFilter, Registry};

/// `service.name` when `OTEL_SERVICE_NAME` is unset.
pub const DEFAULT_OTEL_SERVICE_NAME: &str = "tarka-core";
/// OTLP gRPC endpoint when `OTEL_EXPORTER_OTLP_ENDPOINT` is unset (collector default port).
pub const DEFAULT_OTLP_GRPC_ENDPOINT: &str = "http://127.0.0.1:4317";

/// Clone retained so [`shutdown_tracer`] can call [`SdkTracerProvider::shutdown`] (OpenTelemetry
/// 0.31 does not expose `global::shutdown_tracer_provider`).
static OTEL_SDK_PROVIDER: Mutex<Option<SdkTracerProvider>> = Mutex::new(None);

#[derive(Debug, Error)]
pub enum ObservabilityError {
    #[error("no Tokio runtime handle; call init_tracer under #[tokio::main] or another active Runtime")]
    NoTokioRuntime,
    #[error("OTLP span exporter build failed: {0}")]
    OtlpExporter(#[from] ExporterBuildError),
    #[error("tracing global subscriber already installed: {0}")]
    TracingSubscriber(#[from] tracing_subscriber::util::TryInitError),
}

fn service_name_from_env() -> String {
    std::env::var("OTEL_SERVICE_NAME").unwrap_or_else(|_| DEFAULT_OTEL_SERVICE_NAME.to_string())
}

fn otlp_endpoint_from_env() -> String {
    std::env::var("OTEL_EXPORTER_OTLP_ENDPOINT")
        .or_else(|_| std::env::var("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT"))
        .unwrap_or_else(|_| DEFAULT_OTLP_GRPC_ENDPOINT.to_string())
}

fn export_timeout_from_env() -> Duration {
    std::env::var("OTEL_EXPORTER_OTLP_TRACES_TIMEOUT")
        .or_else(|_| std::env::var("OTEL_EXPORTER_OTLP_TIMEOUT"))
        .ok()
        .and_then(|s| s.parse::<u64>().ok())
        .map(Duration::from_millis)
        .unwrap_or_else(|| Duration::from_secs(10))
}

/// Install a global OpenTelemetry [`SdkTracerProvider`] that exports `tracing` spans to an OTLP
/// collector over **gRPC (tonic)**, and register a [`tracing_subscriber`] stack (env filter + OTLP
/// layer + stderr [`tracing_subscriber::fmt`]).
///
/// # Requirements
///
/// - Call **at most once** per process (same constraint as other `tracing_subscriber` global init).
/// - Must run under an active **Tokio** runtime (`Handle::try_current()` succeeds) so the batch span
///   processor can schedule exports.
///
/// # Environment
///
/// Follows OpenTelemetry exporter conventions where applicable:
///
/// | Variable | Purpose |
/// |----------|---------|
/// | `OTEL_SERVICE_NAME` | `service.name` on the resource (default: [`DEFAULT_OTEL_SERVICE_NAME`]) |
/// | `OTEL_EXPORTER_OTLP_ENDPOINT` or `OTEL_EXPORTER_OTLP_TRACES_ENDPOINT` | Collector URL (default: [`DEFAULT_OTLP_GRPC_ENDPOINT`]) |
/// | `OTEL_EXPORTER_OTLP_TIMEOUT` or `OTEL_EXPORTER_OTLP_TRACES_TIMEOUT` | Export timeout **milliseconds** (default: 10000) |
pub fn init_tracer() -> Result<(), ObservabilityError> {
    let _handle = Handle::try_current().map_err(|_| ObservabilityError::NoTokioRuntime)?;

    let endpoint = otlp_endpoint_from_env();
    let timeout = export_timeout_from_env();
    let service_name = service_name_from_env();

    let exporter = SpanExporter::builder()
        .with_tonic()
        .with_endpoint(endpoint)
        .with_timeout(timeout)
        .build()?;

    let resource = Resource::builder_empty()
        .with_service_name(service_name.clone())
        .build();

    let provider = SdkTracerProvider::builder()
        .with_resource(resource)
        .with_batch_exporter(exporter)
        .build();

    global::set_tracer_provider(provider.clone());
    *OTEL_SDK_PROVIDER
        .lock()
        .unwrap_or_else(|p| p.into_inner()) = Some(provider);

    let tracer = global::tracer(service_name);
    let otel_layer = tracing_opentelemetry::layer().with_tracer(tracer);

    let filter = EnvFilter::try_from_default_env()
        .unwrap_or_else(|_| EnvFilter::new("info,tarka_core=debug"));

    Registry::default()
        .with(filter)
        .with(otel_layer)
        .with(
            tracing_subscriber::fmt::layer()
                .with_target(true)
                .with_level(true)
                .with_writer(std::io::stderr),
        )
        .try_init()?;

    Ok(())
}

/// Shut down the OTLP [`SdkTracerProvider`] installed by [`init_tracer`], flushing processors, then
/// reset the OpenTelemetry global provider to a no-op implementation.
pub fn shutdown_tracer() {
    let mut guard = OTEL_SDK_PROVIDER
        .lock()
        .unwrap_or_else(|p| p.into_inner());
    if let Some(provider) = guard.take() {
        let _ = provider.shutdown();
    }
    global::set_tracer_provider(NoopTracerProvider::new());
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn init_tracer_requires_tokio_runtime() {
        let err = init_tracer().expect_err("sync test thread has no tokio handle");
        assert!(matches!(err, ObservabilityError::NoTokioRuntime));
    }
}
