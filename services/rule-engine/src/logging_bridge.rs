//! Forwards `tracing` events to Python's `logging` module (when a bridge logger is installed).

use parking_lot::Mutex;
use pyo3::prelude::*;
use std::sync::{Arc, LazyLock, Once};

use tracing::{Event, Subscriber};
use tracing_subscriber::layer::{Context, Layer};
use tracing_subscriber::registry::LookupSpan;
use tracing_subscriber::prelude::*;
use tracing_subscriber::util::SubscriberInitExt;

pub type LoggerCell = Arc<Mutex<Option<Py<PyAny>>>>;

pub static LOGGER_BRIDGE: LazyLock<LoggerCell> =
    LazyLock::new(|| Arc::new(Mutex::new(None)));

static TRACING_INIT: Once = Once::new();

/// Install the global `tracing` subscriber once; subsequent calls are no-ops.
pub fn ensure_tracing_installed() {
    TRACING_INIT.call_once(|| {
        let layer = PythonLogBridge {
            logger: LOGGER_BRIDGE.clone(),
        };
        let _ = tracing_subscriber::registry().with(layer).try_init();
    });
}

#[derive(Clone)]
pub struct PythonLogBridge {
    logger: LoggerCell,
}

#[derive(Default)]
struct MessageRecorder {
    message: String,
    /// Structured fields other than `message` (span metadata / key=value context).
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
        let mut line = String::new();
        line.push_str(event.metadata().target());
        line.push_str(": ");
        if rec.message.is_empty() {
            line.push_str(event.metadata().name());
        } else {
            line.push_str(&rec.message);
        }
        for (k, v) in rec.extras {
            use std::fmt::Write;
            let _ = write!(&mut line, " {k}={v}");
        }

        let level = *event.metadata().level();
        let py_level = match level {
            tracing::Level::ERROR => 40_i32,
            tracing::Level::WARN => 30_i32,
            tracing::Level::INFO => 20_i32,
            tracing::Level::DEBUG => 10_i32,
            tracing::Level::TRACE => 5_i32,
        };

        Python::with_gil(|py| {
            let log_call = || -> PyResult<()> {
                let lg = logger.bind(py);
                let _ = lg.call_method1("log", (py_level, line))?;
                Ok(())
            };
            if let Err(e) = log_call() {
                eprintln!("tarka_rule_engine: python logging bridge failed: {e}");
            }
        });
    }
}
