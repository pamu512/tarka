//! Structured JSON logging for ELK/Loki using `tracing`.
//!
//! Events are emitted as single-line JSON objects. Top-level keys `trace_id`,
//! `rule_set_hash`, and `tenant_id` are always present (empty string when no span carries them).
//! Populate these fields by entering a span that records them, for example:
//! `tracing::info_span!("ctx", trace_id = %tid, rule_set_hash = %h, tenant_id = %t)`.

use std::fmt;

use tracing::{Event, Subscriber};
use tracing_serde::fields::AsMap;
use tracing_subscriber::{
    fmt::{
        format::{FormatEvent, JsonFields, Writer},
        time::{FormatTime, SystemTime},
        FmtContext, FormattedFields,
    },
    prelude::*,
    registry::LookupSpan,
    util::SubscriberInitExt,
    EnvFilter, Registry,
};

use crate::loki_tee::SharedDynWriter;

/// Walks the active span scope (root → leaf) and merges `trace_id`, `rule_set_hash`, `tenant_id`
/// from span fields formatted with [`JsonFields`] (same as `tracing_subscriber` JSON formatter).
pub fn merge_trace_context_from_spans<S>(
    ctx: &FmtContext<'_, S, JsonFields>,
) -> (String, String, String)
where
    S: Subscriber + for<'a> LookupSpan<'a>,
{
    let mut trace_id = String::new();
    let mut rule_set_hash = String::new();
    let mut tenant_id = String::new();

    let Some(leaf) = ctx.lookup_current() else {
        return (trace_id, rule_set_hash, tenant_id);
    };

    for span in leaf.scope().from_root() {
        let ext = span.extensions();
        let Some(data) = ext.get::<FormattedFields<JsonFields>>() else {
            continue;
        };
        if data.is_empty() {
            continue;
        }
        let Ok(val) = serde_json::from_str::<serde_json::Value>(data.fields.as_str()) else {
            continue;
        };
        let Some(obj) = val.as_object() else {
            continue;
        };
        if let Some(v) = obj.get("trace_id") {
            trace_id = json_scalar_to_string(v);
        }
        if let Some(v) = obj.get("rule_set_hash") {
            rule_set_hash = json_scalar_to_string(v);
        }
        if let Some(v) = obj.get("tenant_id") {
            tenant_id = json_scalar_to_string(v);
        }
    }

    (trace_id, rule_set_hash, tenant_id)
}

fn json_scalar_to_string(v: &serde_json::Value) -> String {
    match v {
        serde_json::Value::String(s) => s.clone(),
        serde_json::Value::Null => String::new(),
        _ => v.to_string(),
    }
}

/// JSON [`FormatEvent`] that always emits top-level `trace_id`, `rule_set_hash`, and `tenant_id`.
#[derive(Debug, Clone)]
pub struct ElkTracingFormatter {
    timer: SystemTime,
    /// When true, event fields are merged into the root JSON object (typical for log aggregation).
    flatten_event: bool,
}

impl Default for ElkTracingFormatter {
    fn default() -> Self {
        Self {
            timer: SystemTime,
            flatten_event: true,
        }
    }
}

impl ElkTracingFormatter {
    pub fn new() -> Self {
        Self::default()
    }

    pub fn with_flatten_event(mut self, flatten: bool) -> Self {
        self.flatten_event = flatten;
        self
    }
}

impl<S> FormatEvent<S, JsonFields> for ElkTracingFormatter
where
    S: Subscriber + for<'a> LookupSpan<'a>,
{
    fn format_event(
        &self,
        ctx: &FmtContext<'_, S, JsonFields>,
        mut writer: Writer<'_>,
        event: &Event<'_>,
    ) -> fmt::Result {
        let mut timestamp = String::new();
        self.timer
            .format_time(&mut tracing_subscriber::fmt::format::Writer::new(&mut timestamp))
            .map_err(|_| fmt::Error)?;

        let meta = event.metadata();
        let (trace_id, rule_set_hash, tenant_id) = merge_trace_context_from_spans(ctx);

        let mut map = serde_json::Map::new();
        map.insert("timestamp".to_string(), serde_json::Value::String(timestamp));
        map.insert(
            "level".to_string(),
            serde_json::Value::String(meta.level().as_str().to_string()),
        );
        map.insert("trace_id".to_string(), serde_json::Value::String(trace_id));
        map.insert(
            "rule_set_hash".to_string(),
            serde_json::Value::String(rule_set_hash),
        );
        map.insert("tenant_id".to_string(), serde_json::Value::String(tenant_id));
        map.insert(
            "target".to_string(),
            serde_json::Value::String(meta.target().to_string()),
        );

        if self.flatten_event {
            let ev = serde_json::to_value(event.field_map()).map_err(|_| fmt::Error)?;
            if let serde_json::Value::Object(fields) = ev {
                for (k, v) in fields {
                    map.insert(k, v);
                }
            }
        } else {
            map.insert(
                "fields".to_string(),
                serde_json::to_value(event.field_map()).map_err(|_| fmt::Error)?,
            );
        }

        let json =
            serde_json::to_string(&serde_json::Value::Object(map)).map_err(|_| fmt::Error)?;
        write!(writer, "{json}")?;
        writeln!(writer)
    }
}

/// Installs a global subscriber: stdout JSON lines, `RUST_LOG`-style filtering via [`EnvFilter`].
///
/// When `TARKA_LOKI_PUSH_URL` or `LOKI_PUSH_URL` is set, JSON lines are also pushed to Grafana Loki.
pub fn try_install_elk_json_tracing(
) -> Result<(), tracing_subscriber::util::TryInitError> {
    let filter = EnvFilter::try_from_default_env()
        .unwrap_or_else(|_| EnvFilter::new("info"));

    let writer = SharedDynWriter::new(crate::loki_tee::stdout_or_loki_tee());

    Registry::default()
        .with(filter)
        .with(
            tracing_subscriber::fmt::layer()
                .fmt_fields(JsonFields::new())
                .with_timer(SystemTime)
                .event_format(ElkTracingFormatter::default())
                .with_writer(move || writer.clone()),
        )
        .try_init()
}
