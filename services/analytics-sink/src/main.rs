//! Consumes `fraud.decisions.>` from NATS JetStream and inserts rows into ClickHouse.

use anyhow::{Context, Result};
use async_nats::jetstream::{self, consumer::pull, stream::Config as StreamConfig, AckKind};
use axum::{routing::get, Json, Router};
use clickhouse::Row;
use futures::StreamExt;
use serde::Serialize;
use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use std::env;
use std::net::SocketAddr;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;
use std::time::Duration;
use tokio::sync::Mutex;
use tokio::time::{self, MissedTickBehavior};
use tracing::{error, info, warn};

use async_nats::jetstream::Message as JsMessage;

fn analytics_nak_delay() -> std::time::Duration {
    let ms: u64 = env::var("ANALYTICS_CH_NAK_DELAY_MS")
        .ok()
        .and_then(|s| s.parse().ok())
        .unwrap_or(2000);
    std::time::Duration::from_millis(ms.max(1))
}

#[derive(Debug, Serialize)]
struct HealthResponse {
    status: String,
    clickhouse_ok: bool,
    nats_ok: bool,
}

#[derive(Row, Serialize)]
struct FeatureOfflineRow {
    tenant_id: String,
    entity_id: String,
    observed_at: String,
    vector_json: String,
}

#[derive(Row, Serialize)]
struct ShadowScoreRow {
    tenant_id: String,
    trace_id: String,
    payload_json: String,
}

#[derive(Row, Serialize)]
struct ConfigAuditRow {
    payload_json: String,
    row_hash: String,
    prev_hash: String,
}

#[derive(Row, Serialize)]
struct DecisionRow {
    trace_id: String,
    tenant_id: String,
    entity_id: String,
    event_type: String,
    decision: String,
    score: f64,
    tags_json: String,
    rule_hits_json: String,
    payload_json: String,
    created_at: String,
}

async fn ensure_clickhouse(client: &clickhouse::Client) -> Result<()> {
    client
        .query(
            "CREATE TABLE IF NOT EXISTS fraud_decisions (
                trace_id String,
                tenant_id String,
                entity_id String,
                event_type String,
                decision String,
                score Float64,
                tags_json String,
                rule_hits_json String,
                payload_json String,
                created_at String,
                ingested_at DateTime DEFAULT now()
            )
            ENGINE = MergeTree()
            ORDER BY (tenant_id, trace_id)",
        )
        .execute()
        .await
        .context("CREATE TABLE fraud_decisions")?;
    client
        .query(
            "CREATE TABLE IF NOT EXISTS fraud_features_offline (
                tenant_id String,
                entity_id String,
                observed_at String,
                vector_json String,
                ingested_at DateTime DEFAULT now()
            )
            ENGINE = MergeTree()
            ORDER BY (tenant_id, observed_at)",
        )
        .execute()
        .await
        .context("CREATE TABLE fraud_features_offline")?;
    client
        .query(
            "CREATE TABLE IF NOT EXISTS fraud_shadow_scores (
                tenant_id String,
                trace_id String,
                payload_json String,
                ingested_at DateTime DEFAULT now()
            )
            ENGINE = MergeTree()
            ORDER BY (tenant_id, trace_id)",
        )
        .execute()
        .await
        .context("CREATE TABLE fraud_shadow_scores")?;
    client
        .query(
            "CREATE TABLE IF NOT EXISTS fraud_config_audit_chain (
                payload_json String,
                row_hash String,
                prev_hash String,
                ingested_at DateTime DEFAULT now()
            )
            ENGINE = MergeTree()
            ORDER BY (ingested_at)",
        )
        .execute()
        .await
        .context("CREATE TABLE fraud_config_audit_chain")?;
    Ok(())
}

pub(crate) fn json_f64(v: &Value) -> Option<f64> {
    v.as_f64()
        .or_else(|| v.as_i64().map(|i| i as f64))
        .or_else(|| v.as_u64().map(|u| u as f64))
}

pub(crate) fn row_from_decision(v: &Value) -> Option<DecisionRow> {
    Some(DecisionRow {
        trace_id: v.get("trace_id")?.as_str()?.to_string(),
        tenant_id: v.get("tenant_id")?.as_str()?.to_string(),
        entity_id: v.get("entity_id")?.as_str()?.to_string(),
        event_type: v.get("event_type")?.as_str()?.to_string(),
        decision: v.get("decision")?.as_str()?.to_string(),
        score: json_f64(v.get("score")?)?,
        tags_json: serde_json::to_string(v.get("tags").unwrap_or(&json!([]))).unwrap_or_else(|_| "[]".into()),
        rule_hits_json: serde_json::to_string(v.get("rule_hits").unwrap_or(&json!([])))
            .unwrap_or_else(|_| "[]".into()),
        payload_json: serde_json::to_string(v.get("payload").unwrap_or(&json!({}))).unwrap_or_else(|_| "{}".into()),
        created_at: v
            .get("created_at")
            .and_then(|x| x.as_str())
            .unwrap_or("")
            .to_string(),
    })
}

async fn flush_decision_batch(ch: &clickhouse::Client, batch: &mut Vec<(DecisionRow, JsMessage)>) -> Result<()> {
    if batch.is_empty() {
        return Ok(());
    }
    let res = async {
        let mut insert = ch
            .insert("fraud_decisions")
            .context("clickhouse insert begin (batch)")?;
        for (row, _) in batch.iter() {
            insert.write(row).await.context("clickhouse write row")?;
        }
        insert.end().await.context("clickhouse end batch")?;
        Ok::<(), anyhow::Error>(())
    }
    .await;
    if res.is_ok() {
        for (_, msg) in batch.drain(..) {
            let _ = msg.ack().await;
        }
    } else {
        for (_, msg) in batch.drain(..) {
            let _ = msg
                .ack_with(AckKind::Nak(Some(analytics_nak_delay())))
                .await;
        }
    }
    res
}

async fn sink_loop(
    js: jetstream::Context,
    stream_name: String,
    filter_subject: String,
    durable: String,
    ch: clickhouse::Client,
) -> Result<()> {
    let max_rows: usize = env::var("ANALYTICS_BATCH_MAX_ROWS")
        .ok()
        .and_then(|s| s.parse().ok())
        .unwrap_or(5000)
        .max(1);
    let flush_ms: u64 = env::var("ANALYTICS_BATCH_FLUSH_MS")
        .ok()
        .and_then(|s| s.parse().ok())
        .unwrap_or(1000)
        .max(50);

    let stream = js
        .get_or_create_stream(StreamConfig {
            name: stream_name.clone(),
            subjects: vec![filter_subject.clone()],
            ..Default::default()
        })
        .await
        .context("get_or_create_stream decisions")?;

    let consumer = stream
        .get_or_create_consumer::<pull::Config>(
            &durable,
            pull::Config {
                durable_name: Some(durable.clone()),
                filter_subject: filter_subject.clone(),
                ..Default::default()
            },
        )
        .await
        .context("get_or_create_consumer analytics")?;

    info!(
        "analytics-sink consumer {:?} on stream {} filter={} (batch max_rows={} flush_ms={})",
        durable, stream_name, filter_subject, max_rows, flush_ms
    );

    let mut messages = consumer.messages().await.context("consumer.messages")?;
    let mut batch: Vec<(DecisionRow, JsMessage)> = Vec::with_capacity(max_rows.min(1024));
    let mut tick = time::interval(Duration::from_millis(flush_ms));
    tick.set_missed_tick_behavior(MissedTickBehavior::Skip);

    loop {
        tokio::select! {
            _ = tick.tick() => {
                if let Err(e) = flush_decision_batch(&ch, &mut batch).await {
                    error!("batch flush: {}", e);
                }
            }
            maybe = messages.next() => {
                let Some(msg_res) = maybe else { break; };
                let msg = match msg_res {
                    Ok(m) => m,
                    Err(e) => {
                        warn!("message error: {}", e);
                        continue;
                    }
                };
                let data: Value = match serde_json::from_slice(msg.payload.as_ref()) {
                    Ok(v) => v,
                    Err(e) => {
                        warn!("invalid JSON, ack: {}", e);
                        let _ = msg.ack().await;
                        continue;
                    }
                };
                let Some(row) = row_from_decision(&data) else {
                    warn!("skip row: missing required fields");
                    let _ = msg.ack().await;
                    continue;
                };
                batch.push((row, msg));
                if batch.len() >= max_rows {
                    if let Err(e) = flush_decision_batch(&ch, &mut batch).await {
                        error!("batch flush (size): {}", e);
                    }
                }
            }
        }
    }
    let _ = flush_decision_batch(&ch, &mut batch).await;
    Ok(())
}

async fn ensure_misc_stream(js: &jetstream::Context) -> Result<()> {
    js.get_or_create_stream(StreamConfig {
        name: "FRAUD_ANALYTICS_MISC".to_string(),
        subjects: vec![
            "fraud.features.offline".into(),
            "fraud.shadow_ml.>".into(),
            "fraud.audit.config".into(),
        ],
        ..Default::default()
    })
    .await
    .context("get_or_create_stream FRAUD_ANALYTICS_MISC")?;
    Ok(())
}

async fn feature_offline_sink_loop(js: jetstream::Context, ch: clickhouse::Client) -> Result<()> {
    ensure_misc_stream(&js).await?;
    let stream = js.get_stream("FRAUD_ANALYTICS_MISC").await.context("get_stream misc")?;
    let consumer = stream
        .get_or_create_consumer::<pull::Config>(
            "tarka-analytics-features",
            pull::Config {
                durable_name: Some("tarka-analytics-features".into()),
                filter_subject: "fraud.features.offline".into(),
                ..Default::default()
            },
        )
        .await?;
    info!("analytics-sink feature consumer on FRAUD_ANALYTICS_MISC filter=fraud.features.offline");
    let mut messages = consumer.messages().await.context("features consumer.messages")?;
    while let Some(msg_res) = messages.next().await {
        let msg = match msg_res {
            Ok(m) => m,
            Err(e) => {
                warn!("feature message error: {}", e);
                continue;
            }
        };
        let data: Value = match serde_json::from_slice(msg.payload.as_ref()) {
            Ok(v) => v,
            Err(e) => {
                warn!("feature invalid JSON: {}", e);
                let _ = msg.ack().await;
                continue;
            }
        };
        let Some(row) = (|| {
            Some(FeatureOfflineRow {
                tenant_id: data.get("tenant_id")?.as_str()?.to_string(),
                entity_id: data.get("entity_id")?.as_str()?.to_string(),
                observed_at: data
                    .get("observed_at")
                    .and_then(|x| x.as_str())
                    .unwrap_or("")
                    .to_string(),
                vector_json: serde_json::to_string(data.get("feature_vector").unwrap_or(&json!([])))
                    .unwrap_or_else(|_| "[]".into()),
            })
        })() else {
            let _ = msg.ack().await;
            continue;
        };
        let ins = async {
            let mut insert = ch.insert("fraud_features_offline").context("insert features begin")?;
            insert.write(&row).await?;
            insert.end().await?;
            Ok::<(), anyhow::Error>(())
        }
        .await;
        if ins.is_ok() {
            let _ = msg.ack().await;
        } else if let Err(e) = ins {
            warn!("feature insert failed: {}", e);
            let _ = msg
                .ack_with(AckKind::Nak(Some(analytics_nak_delay())))
                .await;
        }
    }
    Ok(())
}

async fn shadow_scores_sink_loop(js: jetstream::Context, ch: clickhouse::Client) -> Result<()> {
    ensure_misc_stream(&js).await?;
    let stream = js.get_stream("FRAUD_ANALYTICS_MISC").await.context("get_stream misc")?;
    let consumer = stream
        .get_or_create_consumer::<pull::Config>(
            "tarka-analytics-shadow",
            pull::Config {
                durable_name: Some("tarka-analytics-shadow".into()),
                filter_subject: "fraud.shadow_ml.>".into(),
                ..Default::default()
            },
        )
        .await?;
    info!("analytics-sink shadow consumer filter=fraud.shadow_ml.>");
    let mut messages = consumer.messages().await.context("shadow consumer.messages")?;
    while let Some(msg_res) = messages.next().await {
        let msg = match msg_res {
            Ok(m) => m,
            Err(e) => {
                warn!("shadow message error: {}", e);
                continue;
            }
        };
        let data: Value = match serde_json::from_slice(msg.payload.as_ref()) {
            Ok(v) => v,
            Err(e) => {
                warn!("shadow invalid JSON: {}", e);
                let _ = msg.ack().await;
                continue;
            }
        };
        let tenant = data
            .get("tenant_id")
            .and_then(|x| x.as_str())
            .unwrap_or("unknown")
            .to_string();
        let trace = data
            .get("trace_id")
            .and_then(|x| x.as_str())
            .unwrap_or("")
            .to_string();
        let row = ShadowScoreRow {
            tenant_id: tenant,
            trace_id: trace,
            payload_json: serde_json::to_string(&data).unwrap_or_else(|_| "{}".into()),
        };
        let ins = async {
            let mut insert = ch.insert("fraud_shadow_scores").context("insert shadow begin")?;
            insert.write(&row).await?;
            insert.end().await?;
            Ok::<(), anyhow::Error>(())
        }
        .await;
        if ins.is_ok() {
            let _ = msg.ack().await;
        } else if let Err(e) = ins {
            warn!("shadow insert failed: {}", e);
            let _ = msg
                .ack_with(AckKind::Nak(Some(analytics_nak_delay())))
                .await;
        }
    }
    Ok(())
}

async fn config_audit_sink_loop(js: jetstream::Context, ch: clickhouse::Client, prev: Arc<Mutex<String>>) -> Result<()> {
    ensure_misc_stream(&js).await?;
    let stream = js.get_stream("FRAUD_ANALYTICS_MISC").await.context("get_stream misc")?;
    let consumer = stream
        .get_or_create_consumer::<pull::Config>(
            "tarka-analytics-config-audit",
            pull::Config {
                durable_name: Some("tarka-analytics-config-audit".into()),
                filter_subject: "fraud.audit.config".into(),
                ..Default::default()
            },
        )
        .await?;
    info!("analytics-sink config audit consumer filter=fraud.audit.config");
    let mut messages = consumer.messages().await.context("audit consumer.messages")?;
    while let Some(msg_res) = messages.next().await {
        let msg = match msg_res {
            Ok(m) => m,
            Err(e) => {
                warn!("audit message error: {}", e);
                continue;
            }
        };
        let data: Value = match serde_json::from_slice(msg.payload.as_ref()) {
            Ok(v) => v,
            Err(e) => {
                warn!("audit invalid JSON: {}", e);
                let _ = msg.ack().await;
                continue;
            }
        };
        let payload_json = serde_json::to_string(&data).unwrap_or_else(|_| "{}".into());
        let prev_hash = prev.lock().await.clone();
        let row_digest = format!("{:x}", Sha256::digest(format!("{prev_hash}:{payload_json}").as_bytes()));
        let row = ConfigAuditRow {
            payload_json,
            row_hash: row_digest.clone(),
            prev_hash: prev_hash.clone(),
        };
        let ins = async {
            let mut insert = ch.insert("fraud_config_audit_chain").context("insert audit begin")?;
            insert.write(&row).await?;
            insert.end().await?;
            Ok::<(), anyhow::Error>(())
        }
        .await;
        if ins.is_ok() {
            *prev.lock().await = row_digest;
            let _ = msg.ack().await;
        } else if let Err(e) = ins {
            warn!("audit insert failed: {}", e);
            let _ = msg
                .ack_with(AckKind::Nak(Some(analytics_nak_delay())))
                .await;
        }
    }
    Ok(())
}

#[tokio::main]
async fn main() -> Result<()> {
    tracing_subscriber::fmt::init();
    dotenvy::dotenv().ok();

    let nats_url = env::var("NATS_URL").unwrap_or_else(|_| "nats://localhost:4222".to_string());
    let clickhouse_host = env::var("CLICKHOUSE_HOST").unwrap_or_else(|_| "localhost".to_string());
    let ch_db = env::var("CLICKHOUSE_DATABASE").unwrap_or_else(|_| "fraud".to_string());
    let stream_name = env::var("DECISIONS_STREAM_NAME").unwrap_or_else(|_| "FRAUD_DECISIONS".to_string());
    let filter_subject = env::var("DECISIONS_SUBJECT_PATTERN").unwrap_or_else(|_| "fraud.decisions.>".to_string());
    let durable = env::var("ANALYTICS_CONSUMER_DURABLE").unwrap_or_else(|_| "tarka-analytics-sink".to_string());

    let ch = clickhouse::Client::default()
        .with_url(format!("http://{}:8123", clickhouse_host))
        .with_database(&ch_db);

    let ch_ok = Arc::new(AtomicBool::new(false));
    let nats_ok = Arc::new(AtomicBool::new(false));

    ensure_clickhouse(&ch).await?;
    ch_ok.store(true, Ordering::Relaxed);
    info!("ClickHouse schema OK (database={})", ch_db);

    info!("Connecting to NATS at {}", nats_url);
    let client = async_nats::connect(&nats_url).await?;
    let js = jetstream::new(client);
    nats_ok.store(true, Ordering::Relaxed);

    let ch_clone = ch.clone();
    let js_clone = js.clone();
    let stream_name_c = stream_name.clone();
    let filter_c = filter_subject.clone();
    let durable_c = durable.clone();
    tokio::spawn(async move {
        if let Err(e) = sink_loop(js_clone, stream_name_c, filter_c, durable_c, ch_clone).await {
            error!("sink loop exited: {}", e);
        }
    });

    let enable_misc = env::var("ANALYTICS_MISC_SINKS")
        .unwrap_or_else(|_| "true".to_string())
        .to_lowercase();
    if matches!(enable_misc.as_str(), "1" | "true" | "yes" | "on") {
        let ch_f = ch.clone();
        let js_f = js.clone();
        tokio::spawn(async move {
            if let Err(e) = feature_offline_sink_loop(js_f, ch_f).await {
                error!("feature sink exited: {}", e);
            }
        });
        let ch_s = ch.clone();
        let js_s = js.clone();
        tokio::spawn(async move {
            if let Err(e) = shadow_scores_sink_loop(js_s, ch_s).await {
                error!("shadow sink exited: {}", e);
            }
        });
        let ch_a = ch.clone();
        let js_a = js.clone();
        let prev = Arc::new(Mutex::new(String::new()));
        tokio::spawn(async move {
            if let Err(e) = config_audit_sink_loop(js_a, ch_a, prev).await {
                error!("config audit sink exited: {}", e);
            }
        });
    }

    let ch_ok_ax = Arc::clone(&ch_ok);
    let nats_ok_ax = Arc::clone(&nats_ok);
    let app = Router::new().route(
        "/v1/health",
        get(move || async move {
            Json(HealthResponse {
                status: "ok".to_string(),
                clickhouse_ok: ch_ok_ax.load(Ordering::Relaxed),
                nats_ok: nats_ok_ax.load(Ordering::Relaxed),
            })
        }),
    );

    let port = env::var("PORT").unwrap_or_else(|_| "8008".to_string());
    let addr: SocketAddr = format!("0.0.0.0:{}", port).parse()?;
    info!("Listening on {}", addr);
    let listener = tokio::net::TcpListener::bind(addr).await?;
    axum::serve(listener, app).await?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::row_from_decision;
    use serde_json::json;

    #[test]
    fn row_from_decision_parses_minimal_payload() {
        let v = json!({
            "trace_id": "t1",
            "tenant_id": "acme",
            "entity_id": "u1",
            "event_type": "payment",
            "decision": "allow",
            "score": 12.5,
            "tags": ["a"],
            "rule_hits": ["r1"],
            "payload": {"amount": 1},
            "created_at": "2026-01-01T00:00:00Z"
        });
        let row = row_from_decision(&v).expect("row");
        assert_eq!(row.tenant_id, "acme");
        assert_eq!(row.score, 12.5);
    }
}

#[cfg(test)]
mod proptests {
    use super::json_f64;
    use proptest::prelude::*;
    use serde_json::json;

    proptest! {
        #[test]
        fn json_f64_never_panics(n in any::<i64>()) {
            let v = json!(n);
            let _ = json_f64(&v);
        }
    }
}
