//! Forwards `tracing` events to Python's `logging` module (when a bridge logger is installed).
//! Each line is a single JSON object including mandatory `trace_id`, `rule_set_hash`, `tenant_id`,
//! and `otel_trace_id` (W3C 128-bit trace id for Evidence Manifest correlation).
//!
//! When `SENTRY_DSN` or `TARKA_SENTRY_DSN` is set, [`sentry_tracing`] is layered so panics and span
//! metadata reach Sentry with the same correlation fields.

use std::borrow::Cow;
use std::cell::RefCell;
use std::io::Write;
use std::sync::{Arc, LazyLock, Once, OnceLock};

use parking_lot::Mutex;
use pyo3::prelude::*;
use serde_json::json;
use tracing::{Event, Subscriber};
use tracing_subscriber::layer::{Context, Layer};
use tracing_subscriber::registry::LookupSpan;
use tracing_subscriber::prelude::*;
use tracing_subscriber::util::SubscriberInitExt;

pub type LoggerCell = Arc<Mutex<Option<Py<PyAny>>>>;

pub static LOGGER_BRIDGE: LazyLock<LoggerCell> =
    LazyLock::new(|| Arc::new(Mutex::new(None)));

thread_local! {
    /// Mirrors FastAPI `structlog` context when Python calls [`set_tracing_log_context`].
    static TRACE_TLS: RefCell<(String, String, String, String)> =
        RefCell::new((String::new(), String::new(), String::new(), String::new()));
}

static TRACING_INIT: Once = Once::new();

/// Keeps the Sentry client alive for the process lifetime (required when DSN is set).
static SENTRY_GUARD: OnceLock<sentry::ClientInitGuard> = OnceLock::new();

fn init_sentry_if_configured() {
    let _ = SENTRY_GUARD.get_or_init(|| {
        let dsn = std::env::var("SENTRY_DSN")
            .or_else(|_| std::env::var("TARKA_SENTRY_DSN"))
            .unwrap_or_default();
        let trimmed = dsn.trim();
        if trimmed.is_empty() {
            return sentry::init(());
        }
        let release = option_env!("CARGO_PKG_VERSION").map(|v| {
            Cow::Owned(format!("tarka_rule_engine@{v}"))
        });
        let environment = std::env::var("SENTRY_ENVIRONMENT")
            .ok()
            .map(|s| Cow::Owned(s));
        sentry::init((
            trimmed,
            sentry::ClientOptions {
                release,
                environment,
                ..Default::default()
            },
        ))
    });
}

/// Thread-local trace correlation for Rust → Python log forwarding (same thread as the caller).
#[pyfunction]
#[pyo3(name = "set_tracing_log_context")]
#[pyo3(signature = (trace_id, rule_set_hash, tenant_id, otel_trace_id=None))]
pub fn set_tracing_log_context_py(
    trace_id: String,
    rule_set_hash: String,
    tenant_id: String,
    otel_trace_id: Option<String>,
) {
    let otel = otel_trace_id.unwrap_or_default();
    TRACE_TLS.with(|c| {
        *c.borrow_mut() = (trace_id, rule_set_hash, tenant_id, otel);
    });
}

pub(crate) fn eval_context_span(tenant_for_log: &str) -> tracing::Span {
    let (a, b, mut c, d) = TRACE_TLS.with(|x| x.borrow().clone());
    if !tenant_for_log.is_empty() {
        c = tenant_for_log.to_string();
    }
    tracing::info_span!(
        "tarka_rule_engine_eval",
        trace_id = %a,
        rule_set_hash = %b,
        tenant_id = %c,
        otel_trace_id = %d
    )
}

/// Install the global `tracing` subscriber once; subsequent calls are no-ops.
pub fn ensure_tracing_installed() {
    TRACING_INIT.call_once(|| {
        init_sentry_if_configured();
        let sentry_layer = sentry_tracing::layer();
        let python_layer = PythonLogBridge {
            logger: LOGGER_BRIDGE.clone(),
        };
        let _ = tracing_subscriber::registry()
            .with(sentry_layer)
            .with(python_layer)
            .try_init();
    });
}

#[derive(Clone)]
pub struct PythonLogBridge {
    logger: LoggerCell,
}

#[derive(Default)]
struct MessageRecorder {
    message: String,
    extras: Vec<(String, String)>,
}

impl MessageRecorder {
    fn push_extra(&mut self, name: &str, value: String) {
        if name == "message" {
            if self.message.is_empty() {
                self.message = value;
            } else {
                self.message.push_str(&value);
            }
        } else {
            self.extras.push((name.to_string(), value));
        }
    }
}

impl tracing::field::Visit for MessageRecorder {
    fn record_debug(&mut self, field: &tracing::field::Field, value: &dyn std::fmt::Debug) {
        use std::fmt::Write;
        let mut buf = String::new();
        let _ = write!(&mut buf, "{value:?}");
        self.push_extra(field.name(), buf);
    }

    fn record_str(&mut self, field: &tracing::field::Field, value: &str) {
        self.push_extra(field.name(), value.to_string());
    }

    fn record_i64(&mut self, field: &tracing::field::Field, value: i64) {
        self.push_extra(field.name(), format!("{value}"));
    }

    fn record_u64(&mut self, field: &tracing::field::Field, value: u64) {
        self.push_extra(field.name(), format!("{value}"));
    }

    fn record_bool(&mut self, field: &tracing::field::Field, value: bool) {
        self.push_extra(field.name(), format!("{value}"));
    }

    fn record_f64(&mut self, field: &tracing::field::Field, value: f64) {
        self.push_extra(field.name(), format!("{value}"));
    }
}

impl<S> Layer<S> for PythonLogBridge
where
    S: Subscriber + for<'a> LookupSpan<'a>,
{
    fn on_event(&self, event: &Event<'_>, _ctx: Context<'_, S>) {
        let guard = self.logger.lock();
        let Some(logger) = guard.as_ref() else {
            return;
        };

        let mut rec = MessageRecorder::default();
        event.record(&mut rec);

        let (tls_tid, tls_rsh, tls_ten, tls_otel) =
            TRACE_TLS.with(|c| c.borrow().clone());

        let mut fields = serde_json::Map::new();
        for (k, v) in rec.extras {
            fields.insert(k, json!(v));
        }
        if !rec.message.is_empty() {
            fields.insert("message".to_string(), json!(rec.message));
        } else {
            fields.insert(
                "message".to_string(),
                json!(event.metadata().name()),
            );
        }

        let level = *event.metadata().level();
        let level_str = match level {
            tracing::Level::ERROR => "ERROR",
            tracing::Level::WARN => "WARN",
            tracing::Level::INFO => "INFO",
            tracing::Level::DEBUG => "DEBUG",
            tracing::Level::TRACE => "TRACE",
        };

        let py_level = match level {
            tracing::Level::ERROR => 40_i32,
            tracing::Level::WARN => 30_i32,
            tracing::Level::INFO => 20_i32,
            tracing::Level::DEBUG => 10_i32,
            tracing::Level::TRACE => 5_i32,
        };

        let line = json!({
            "ts": chrono::Utc::now().to_rfc3339_opts(chrono::SecondsFormat::Millis, true),
            "level": level_str,
            "trace_id": tls_tid,
            "rule_set_hash": tls_rsh,
            "tenant_id": tls_ten,
            "otel_trace_id": tls_otel,
            "target": event.metadata().target(),
            "fields": serde_json::Value::Object(fields),
        })
        .to_string();

        Python::with_gil(|py| {
            let log_call = || -> PyResult<()> {
                let lg = logger.bind(py);
                let _ = lg.call_method1("log", (py_level, line))?;
                Ok(())
            };
            if let Err(e) = log_call() {
                let err_json = json!({
                    "ts": chrono::Utc::now().to_rfc3339_opts(chrono::SecondsFormat::Millis, true),
                    "level": "ERROR",
                    "trace_id": "",
                    "rule_set_hash": "",
                    "tenant_id": "",
                    "otel_trace_id": "",
                    "target": "tarka_rule_engine.logging_bridge",
                    "message": format!("python logging bridge failed: {e}"),
                });
                let _ = writeln!(std::io::stderr(), "{err_json}");
            }
        });
    }
}
