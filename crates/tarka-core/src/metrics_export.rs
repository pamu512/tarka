//! Prometheus-oriented metric hooks (`metrics` facade + optional HTTP scrape endpoint).
//!
//! Metric names match operator-facing Prometheus identifiers:
//! - `rules_evaluated_total` — leaf trace steps recorded (one per evaluated rule leaf).
//! - `engine_latency_histogram` — [`crate::engine::Evaluator::evaluate`] **rule evaluation** phase
//!   only: from entry through return of `eval_expr` (seconds), before trace finalize / manifest build.
//! - `tarka.engine.processing_time` — full wall time inside [`crate::engine::Evaluator::evaluate`]
//!   (seconds): `eval_expr`, trace finalize, and manifest assembly for this call — **excludes** host
//!   FFI (PyO3 wrapper, JSON parse outside the evaluator, KMS, etc.).
//! - `buffer_utilization_ratio` — gauge in \[0, 1\] vs [`TRACE_BUFFER_CAPACITY_HINT`] (SegQueue is unbounded).
//! - `manifest_generation_errors` — evaluation ended without a full [`crate::evidence::EvidenceManifest`].
//!
//! With feature **`prometheus`**, call [`install_prometheus_exporter`] once per process; the HTTP
//! listener serves Prometheus text on **any** `GET` path (e.g. `http://host:9090/metrics`).
//!
//! ```ignore
//! # #[cfg(feature = "prometheus")]
//! tarka_core::install_prometheus_exporter("0.0.0.0:9090".parse().unwrap())?;
//! ```

/// Soft ceiling used only for [`buffer_utilization_ratio`] (trace queue has no fixed capacity).
pub const TRACE_BUFFER_CAPACITY_HINT: u64 = 4096;

/// Increment after each successful [`crate::engine::trace::TraceContext::record_step`] (leaf evaluation).
#[inline]
pub fn record_rules_evaluated(count: u64) {
    if count > 0 {
        metrics::counter!("rules_evaluated_total").increment(count);
    }
}

/// Observe [`crate::engine::Evaluator::evaluate`] **evaluation phase** latency in seconds (`eval_expr` only).
#[inline]
pub fn record_engine_latency_histogram_seconds(seconds: f64) {
    if seconds >= 0.0 {
        metrics::histogram!("engine_latency_histogram").record(seconds);
    }
}

/// Histogram of wall time spent inside [`crate::engine::Evaluator::evaluate`] (seconds).
///
/// Covers `eval_expr`, trace finalization, and manifest construction for this invocation. Excludes
/// any time before/after this Rust method (FFI, JSON parsing in the host, KMS signing after return, …).
#[inline]
pub fn record_tarka_engine_processing_time_seconds(seconds: f64) {
    if seconds >= 0.0 {
        metrics::histogram!("tarka.engine.processing_time").record(seconds);
    }
}

/// Update gauge relative to [`TRACE_BUFFER_CAPACITY_HINT`] (clamped to 1.0).
#[inline]
pub fn set_buffer_utilization_ratio(depth: u64) {
    let ratio = (depth as f64 / TRACE_BUFFER_CAPACITY_HINT as f64).min(1.0);
    metrics::gauge!("buffer_utilization_ratio").set(ratio);
}

#[inline]
pub fn record_manifest_generation_error() {
    metrics::counter!("manifest_generation_errors").increment(1);
}

/// Install the global metrics recorder and bind an HTTP scrape listener on `bind` for Prometheus.
///
/// `metrics-exporter-prometheus` answers **`GET` on any path** with the exposition payload (use `/metrics`
/// in Prometheus `metrics_path` or `curl http://…/metrics`).
///
/// Call at most once per process. Requires crate feature **`prometheus`**.
#[cfg(feature = "prometheus")]
pub fn install_prometheus_exporter(
    bind: std::net::SocketAddr,
) -> Result<(), PrometheusInstallError> {
    metrics_exporter_prometheus::PrometheusBuilder::new()
        .with_http_listener(bind)
        .install()
        .map_err(|e| PrometheusInstallError(e.to_string()))
}

#[cfg(feature = "prometheus")]
#[derive(Debug, Clone)]
pub struct PrometheusInstallError(pub String);

#[cfg(feature = "prometheus")]
impl std::fmt::Display for PrometheusInstallError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "{}", self.0)
    }
}

#[cfg(feature = "prometheus")]
impl std::error::Error for PrometheusInstallError {}
