//! Event ingest: `POST /v1/events` → NATS JetStream; pull consumer → `POST /v1/decisions/evaluate`.

use anyhow::{Context, Result};
use async_nats::jetstream::{self, consumer::pull, stream::Config as StreamConfig, AckKind};
use axum::{
    body::Bytes,
    extract::State,
    http::{header::HeaderMap, StatusCode},
    response::{IntoResponse, Response},
    routing::{get, post},
    Json, Router,
};
use futures::StreamExt;
use reqwest::Client;
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use std::env;
use std::net::SocketAddr;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;
use tracing::{error, info, warn};

const VALID_EVENT_TYPES: &[&str] = &[
    "login", "payment", "signup", "device", "session", "custom",
];

#[derive(Clone)]
struct AppState {
    js: jetstream::Context,
    stream_name: String,
    subject_prefix: String,
    decision_api_url: String,
    http: Client,
    upstream_api_key: Option<String>,
    envelope_mode: String,
    require_idempotency_key: bool,
    nats_ready: Arc<AtomicBool>,
    /// JetStream subject for 4xx responses from decision-api (replay / ops).
    dlq_subject: String,
    /// Optional subject for poison-pill messages (invalid JSON, etc.).
    deadletter_subject: Option<String>,
    /// When true, mask common PII scalar fields on ingested events before NATS publish.
    pii_tokenize: bool,
}

#[derive(Debug, Serialize)]
struct HealthResponse {
    status: String,
    nats_ok: bool,
}

#[derive(Debug, Serialize)]
struct ReadyResponse {
    status: String,
    nats_ok: bool,
}

async fn health_check(State(st): State<Arc<AppState>>) -> Json<HealthResponse> {
    Json(HealthResponse {
        status: "ok".to_string(),
        nats_ok: st.nats_ready.load(Ordering::Relaxed),
    })
}

async fn ready_check(State(st): State<Arc<AppState>>) -> Result<Json<ReadyResponse>, StatusCode> {
    if !st.nats_ready.load(Ordering::Relaxed) {
        return Err(StatusCode::SERVICE_UNAVAILABLE);
    }
    Ok(Json(ReadyResponse {
        status: "ok".to_string(),
        nats_ok: true,
    }))
}

fn require_ingest_auth(headers: &HeaderMap) -> Result<(), StatusCode> {
    let keys_raw = env::var("API_KEYS").unwrap_or_default();
    let keys: Vec<String> = keys_raw
        .split(',')
        .map(|s| s.trim().to_string())
        .filter(|s| !s.is_empty())
        .collect();
    if keys.is_empty() {
        let allow = env::var("ALLOW_INSECURE_NO_AUTH")
            .unwrap_or_default()
            .to_lowercase();
        if matches!(allow.as_str(), "1" | "true" | "yes" | "on") {
            return Ok(());
        }
        return Err(StatusCode::SERVICE_UNAVAILABLE);
    }
    let hk = headers
        .get("x-api-key")
        .or_else(|| headers.get("X-Api-Key"))
        .and_then(|v| v.to_str().ok())
        .unwrap_or("");
    if !keys.iter().any(|k| k == hk) {
        return Err(StatusCode::UNAUTHORIZED);
    }
    Ok(())
}

fn extract_event_json(body: &Value, mode: &str) -> Result<Value, String> {
    match mode {
        "required" => {
            if body.get("schema_version").and_then(|v| v.as_str()) != Some("1") {
                return Err("ingest_envelope_invalid".into());
            }
            body.get("event")
                .cloned()
                .ok_or_else(|| "ingest_event_missing".into())
        }
        _ => {
            if body.get("schema_version").is_some() || body.get("event").is_some() {
                body.get("event")
                    .cloned()
                    .ok_or_else(|| "ingest_event_missing".into())
            } else {
                Ok(body.clone())
            }
        }
    }
}

fn pii_digest_token(s: &str) -> String {
    let h = Sha256::digest(s.as_bytes());
    let hex12: String = h[..12].iter().map(|b| format!("{:02x}", b)).collect();
    format!("tok_{hex12}")
}

fn tokenize_pii_scalar(v: &mut Value) {
    if let Value::String(s) = v {
        if s.is_empty() {
            return;
        }
        *v = Value::String(pii_digest_token(s));
    }
}

/// Tokenize common scalar PII fields under ``payload`` and top-level event keys (ingress hardening).
fn tokenize_pii_in_event(ev: &mut Value) {
    const KEYS: &[&str] = &[
        "email",
        "phone",
        "phone_number",
        "ssn",
        "tax_id",
        "ip_address",
        "shipping_address",
        "billing_address",
    ];
    fn walk(obj: &mut serde_json::Map<String, Value>, depth: usize) {
        if depth > 6 {
            return;
        }
        for (k, v) in obj.iter_mut() {
            let lk = k.to_ascii_lowercase();
            if KEYS.iter().any(|key| *key == lk.as_str()) {
                tokenize_pii_scalar(v);
            } else if let Some(inner) = v.as_object_mut() {
                walk(inner, depth + 1);
            } else if let Some(arr) = v.as_array_mut() {
                for item in arr.iter_mut().take(64) {
                    if let Some(io) = item.as_object_mut() {
                        walk(io, depth + 1);
                    }
                }
            }
        }
    }
    if let Some(root) = ev.as_object_mut() {
        if let Some(payload) = root.get_mut("payload").and_then(|x| x.as_object_mut()) {
            walk(payload, 0);
        }
        walk(root, 0);
    }
}

const MAX_JSON_DEPTH: usize = 48;

fn json_depth_exceeds(v: &Value, max_depth: usize) -> bool {
    fn walk(v: &Value, depth: usize, max_depth: usize) -> bool {
        if depth > max_depth {
            return true;
        }
        match v {
            Value::Array(a) => a.iter().any(|x| walk(x, depth + 1, max_depth)),
            Value::Object(o) => o.values().any(|x| walk(x, depth + 1, max_depth)),
            _ => false,
        }
    }
    walk(v, 0, max_depth)
}

fn validate_evaluate_shape(ev: &Value) -> Result<(), String> {
    let tenant = ev.get("tenant_id").and_then(|v| v.as_str()).ok_or("tenant_id")?;
    if tenant.is_empty() {
        return Err("tenant_id_empty".into());
    }
    let et = ev
        .get("event_type")
        .and_then(|v| v.as_str())
        .ok_or("event_type")?;
    if !VALID_EVENT_TYPES.contains(&et) {
        return Err("ingest_event_type_invalid".into());
    }
    let eid = ev.get("entity_id").and_then(|v| v.as_str()).ok_or("entity_id")?;
    if eid.is_empty() {
        return Err("entity_id_empty".into());
    }
    Ok(())
}

async fn publish_deadletter_record(js: &jetstream::Context, subject: &str, record: Value) {
    if let Ok(bytes) = serde_json::to_vec(&record) {
        if let Ok(ackf) = js.publish(subject.to_string(), bytes.into()).await {
            let _ = ackf.await;
        }
    }
}

fn event_subject(prefix: &str, ev: &Value) -> String {
    let tenant = ev.get("tenant_id").and_then(|v| v.as_str()).unwrap_or("unknown");
    let et = ev
        .get("event_type")
        .and_then(|v| v.as_str())
        .unwrap_or("unknown");
    format!("{}.{}.{}", prefix, tenant, et)
}

async fn post_events(
    State(st): State<Arc<AppState>>,
    headers: HeaderMap,
    body: Bytes,
) -> Response {
    if let Err(code) = require_ingest_auth(&headers) {
        return code.into_response();
    }
    let body: Value = match serde_json::from_slice(&body) {
        Ok(v) => v,
        Err(e) => {
            return (
                StatusCode::BAD_REQUEST,
                Json(json!({"error": "invalid_json", "detail": e.to_string()})),
            )
                .into_response();
        }
    };
    if st.require_idempotency_key {
        let idem = headers
            .get("idempotency-key")
            .or_else(|| headers.get("Idempotency-Key"))
            .and_then(|v| v.to_str().ok())
            .unwrap_or("")
            .trim();
        let meta_key = body
            .get("metadata")
            .and_then(|m| m.get("idempotency_key"))
            .and_then(|v| v.as_str())
            .unwrap_or("")
            .trim();
        if idem.is_empty() && meta_key.is_empty() {
            return (
                StatusCode::UNPROCESSABLE_ENTITY,
                Json(json!({
                    "error": "ingest_idempotency_key_required",
                    "reason_codes": ["ingest_idempotency_key_required"]
                })),
            )
                .into_response();
        }
    }
    let mut ev = match extract_event_json(&body, &st.envelope_mode) {
        Ok(v) => v,
        Err(code) => {
            return (
                StatusCode::UNPROCESSABLE_ENTITY,
                Json(json!({"error": code, "reason_codes": [code]})),
            )
                .into_response();
        }
    };
    if env::var("INGEST_REQUIRE_SCHEMA_ID")
        .unwrap_or_default()
        .to_lowercase()
        .chars()
        .any(|c| matches!(c, '1' | 't' | 'y'))
        && ev
            .get("schema_id")
            .and_then(|v| v.as_str())
            .map(|s| s.trim().is_empty())
            .unwrap_or(true)
    {
        return (
            StatusCode::UNPROCESSABLE_ENTITY,
            Json(json!({"error": "schema_id_required", "reason_codes": ["schema_registry:missing_schema_id"]})),
        )
            .into_response();
    }
    if let Err(code) = validate_evaluate_shape(&ev) {
        let rc = if code == "ingest_event_type_invalid" {
            "ingest_event_type_invalid"
        } else {
            "ingest_validation_failed"
        };
        return (
            StatusCode::UNPROCESSABLE_ENTITY,
            Json(json!({"error": code, "reason_codes": [rc]})),
        )
            .into_response();
    }
    if st.pii_tokenize {
        tokenize_pii_in_event(&mut ev);
    }
    let ingest_id = uuid::Uuid::new_v4().to_string();
    let envelope = json!({
        "ingest_id": ingest_id,
        "evaluate_request": ev,
    });
    let subject = event_subject(&st.subject_prefix, &envelope["evaluate_request"]);
    let payload = match serde_json::to_vec(&envelope) {
        Ok(p) => p,
        Err(e) => {
            error!("serialize ingest envelope failed: {}", e);
            return (
                StatusCode::INTERNAL_SERVER_ERROR,
                Json(json!({"error": "serialize_failed", "detail": e.to_string()})),
            )
                .into_response();
        }
    };
    let ack = match st.js.publish(subject.clone(), payload.into()).await {
        Ok(fut) => match fut.await {
            Ok(a) => a,
            Err(e) => {
                error!("NATS publish ack failed: {}", e);
                return (
                    StatusCode::BAD_GATEWAY,
                    Json(json!({"error": "nats_publish_failed", "detail": e.to_string()})),
                )
                    .into_response();
            }
        },
        Err(e) => {
            error!("NATS publish failed: {}", e);
            return (
                StatusCode::BAD_GATEWAY,
                Json(json!({"error": "nats_publish_failed", "detail": e.to_string()})),
            )
                .into_response();
        }
    };
    Json(json!({
        "accepted": true,
        "stream_seq": ack.sequence,
        "ingest_id": ingest_id,
    }))
    .into_response()
}

#[derive(Debug, Deserialize)]
struct BatchBody {
    events: Vec<Value>,
}

async fn post_events_batch(
    State(st): State<Arc<AppState>>,
    headers: HeaderMap,
    body: Bytes,
) -> Response {
    if let Err(code) = require_ingest_auth(&headers) {
        return code.into_response();
    }
    let parsed: BatchBody = match serde_json::from_slice(&body) {
        Ok(v) => v,
        Err(e) => {
            return (
                StatusCode::BAD_REQUEST,
                Json(json!({"error": "invalid_json", "detail": e.to_string()})),
            )
                .into_response();
        }
    };
    let mut results = Vec::new();
    for item in parsed.events {
        let mut ev = match extract_event_json(&item, &st.envelope_mode) {
            Ok(v) => v,
            Err(code) => {
                return (
                    StatusCode::UNPROCESSABLE_ENTITY,
                    Json(json!({"error": code, "reason_codes": [code]})),
                )
                    .into_response();
            }
        };
        if let Err(code) = validate_evaluate_shape(&ev) {
            return (
                StatusCode::UNPROCESSABLE_ENTITY,
                Json(json!({"error": code})),
            )
                .into_response();
        }
        if st.pii_tokenize {
            tokenize_pii_in_event(&mut ev);
        }
        let ingest_id = uuid::Uuid::new_v4().to_string();
        let envelope = json!({
            "ingest_id": ingest_id,
            "evaluate_request": ev,
        });
        let subject = event_subject(&st.subject_prefix, &envelope["evaluate_request"]);
        let payload = match serde_json::to_vec(&envelope) {
            Ok(p) => p,
            Err(e) => {
                return (
                    StatusCode::INTERNAL_SERVER_ERROR,
                    Json(json!({"error": "serialize_failed", "detail": e.to_string()})),
                )
                    .into_response();
            }
        };
        let ack = match st.js.publish(subject, payload.into()).await {
            Ok(fut) => match fut.await {
                Ok(a) => a,
                Err(e) => {
                    error!("NATS publish ack failed: {}", e);
                    return (
                        StatusCode::BAD_GATEWAY,
                        Json(json!({"error": "nats_publish_failed", "detail": e.to_string()})),
                    )
                        .into_response();
                }
            },
            Err(e) => {
                error!("NATS publish failed: {}", e);
                return (
                    StatusCode::BAD_GATEWAY,
                    Json(json!({"error": "nats_publish_failed", "detail": e.to_string()})),
                )
                    .into_response();
            }
        };
        results.push(json!({"ingest_id": ingest_id, "seq": ack.sequence}));
    }
    Json(json!({"accepted": results.len(), "results": results})).into_response()
}

async fn stream_info(
    State(st): State<Arc<AppState>>,
    headers: HeaderMap,
) -> Result<Json<Value>, StatusCode> {
    require_ingest_auth(&headers)?;
    let mut stream = st.js.get_stream(&st.stream_name).await.map_err(|_| {
        warn!("stream_info: get_stream failed");
        StatusCode::SERVICE_UNAVAILABLE
    })?;
    let info = stream.info().await.map_err(|_| StatusCode::SERVICE_UNAVAILABLE)?;
    Ok(Json(json!({
        "stream": info.config.name,
        "messages": info.state.messages,
        "bytes": info.state.bytes,
        "first_seq": info.state.first_sequence,
        "last_seq": info.state.last_sequence,
        "consumer_count": info.state.consumer_count,
    })))
}

async fn evaluate_consumer_loop(st: Arc<AppState>) -> Result<()> {
    let stream = st
        .js
        .get_stream(&st.stream_name)
        .await
        .context("get_stream for consumer")?;
    let filter = format!("{}.>", st.subject_prefix);
    let durable = env::var("INGEST_CONSUMER_DURABLE").unwrap_or_else(|_| "tarka-ingest-eval".to_string());
    let consumer = stream
        .get_or_create_consumer::<pull::Config>(
            &durable,
            pull::Config {
                durable_name: Some(durable.clone()),
                filter_subject: filter.clone(),
                ..Default::default()
            },
        )
        .await
        .context("get_or_create_consumer")?;
    info!("JetStream pull consumer {:?} ready (filter={})", durable, filter);
    let mut messages = consumer
        .messages()
        .await
        .context("consumer.messages()")?;
    let eval_url = format!("{}/v1/decisions/evaluate", st.decision_api_url.trim_end_matches('/'));
    while let Some(msg) = messages.next().await {
        let msg = match msg {
            Ok(m) => m,
            Err(e) => {
                warn!("consumer message error: {}", e);
                continue;
            }
        };
        let data: Value = match serde_json::from_slice(msg.payload.as_ref()) {
            Ok(v) => v,
            Err(e) => {
                warn!("skip invalid JSON: {}", e);
                if let Some(ref dl_sub) = st.deadletter_subject {
                    let tomb = json!({
                        "kind": "json_parse_error",
                        "error": e.to_string(),
                        "payload_utf8_lossy": String::from_utf8_lossy(msg.payload.as_ref()).chars().take(8000).collect::<String>(),
                    });
                    publish_deadletter_record(&st.js, dl_sub, tomb).await;
                }
                let _ = msg.ack().await;
                continue;
            }
        };
        if json_depth_exceeds(&data, MAX_JSON_DEPTH) {
            warn!("deadletter: envelope JSON depth exceeds {}", MAX_JSON_DEPTH);
            if let Some(ref dl_sub) = st.deadletter_subject {
                publish_deadletter_record(
                    &st.js,
                    dl_sub,
                    json!({"kind": "depth_exceeded", "max_depth": MAX_JSON_DEPTH, "preview": data.to_string().chars().take(4000).collect::<String>()}),
                )
                .await;
            }
            let _ = msg.ack().await;
            continue;
        }
        let inner = data
            .get("evaluate_request")
            .cloned()
            .or_else(|| data.get("event").cloned());
        let Some(mut body) = inner else {
            warn!("skip: no evaluate_request/event");
            if let Some(ref dl_sub) = st.deadletter_subject {
                publish_deadletter_record(
                    &st.js,
                    dl_sub,
                    json!({"kind": "missing_evaluate_request", "envelope": data}),
                )
                .await;
            }
            let _ = msg.ack().await;
            continue;
        };
        if let Err(reason) = validate_evaluate_shape(&body) {
            warn!("deadletter: schema violation {}", reason);
            if let Some(ref dl_sub) = st.deadletter_subject {
                publish_deadletter_record(
                    &st.js,
                    dl_sub,
                    json!({"kind": "schema_violation", "reason": reason, "body": body}),
                )
                .await;
            }
            let _ = msg.ack().await;
            continue;
        };
        if let Some(obj) = body.as_object_mut() {
            obj.remove("_ingest_id");
        }
        let mut req = st.http.post(&eval_url).json(&body);
        if let Some(h) = msg.headers.as_ref() {
            if let Some(tp) = h.get("traceparent").and_then(|v| std::str::from_utf8(v.as_ref()).ok()) {
                req = req.header("traceparent", tp);
            }
        }
        if let Some(ref k) = st.upstream_api_key {
            if !k.is_empty() {
                req = req.header("x-api-key", k);
            }
        }
        match req.send().await {
            Ok(resp) => {
                let code = resp.status();
                if code.is_success() {
                    let _ = msg.ack().await;
                } else if code.as_u16() >= 500 {
                    warn!("evaluate {} — nack for retry", code);
                    let _ = msg.ack_with(AckKind::Nak(None)).await;
                } else {
                    let detail = resp.text().await.unwrap_or_default();
                    let dlq = json!({
                        "kind": "evaluate_client_error",
                        "status": code.as_u16(),
                        "evaluate_url": eval_url,
                        "upstream_body_preview": detail.chars().take(4000).collect::<String>(),
                        "envelope": data,
                    });
                    if let Ok(bytes) = serde_json::to_vec(&dlq) {
                        let js = st.js.clone();
                        let subj = st.dlq_subject.clone();
                        match js.publish(subj, bytes.into()).await {
                            Ok(fut) => {
                                if let Err(pe) = fut.await {
                                    warn!("DLQ publish ack failed: {}", pe);
                                }
                            }
                            Err(pe) => warn!("DLQ publish failed: {}", pe),
                        }
                    }
                    let _ = msg.ack().await;
                }
            }
            Err(e) => {
                warn!("evaluate request error: {} — nack", e);
                let _ = msg.ack_with(AckKind::Nak(None)).await;
            }
        }
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::{json_depth_exceeds, tokenize_pii_in_event, validate_evaluate_shape};
    use serde_json::json;

    #[test]
    fn json_depth_detects_deep_nesting() {
        let mut inner = json!("x");
        for _ in 0..60 {
            inner = json!({ "k": inner });
        }
        assert!(json_depth_exceeds(&inner, 48));
    }

    #[test]
    fn validate_evaluate_shape_ok() {
        let ev = json!({
            "tenant_id": "t1",
            "entity_id": "e1",
            "event_type": "payment",
            "payload": {}
        });
        assert!(validate_evaluate_shape(&ev).is_ok());
    }

    #[test]
    fn tokenize_rewrites_email_field() {
        let mut ev = json!({
            "tenant_id": "t1",
            "entity_id": "e1",
            "event_type": "payment",
            "payload": {"email": "user@example.com"}
        });
        tokenize_pii_in_event(&mut ev);
        let em = ev["payload"]["email"].as_str().unwrap();
        assert!(em.starts_with("tok_"));
        assert!(!em.contains('@'));
    }
}

#[cfg(test)]
mod proptests {
    use super::validate_evaluate_shape;
    use proptest::prelude::*;
    use serde_json::json;

    proptest! {
        #[test]
        fn validate_rejects_bad_event_type_suffix(suffix in prop::string::string_regex("[0-9]{1,6}").unwrap()) {
            let et = format!("not_a_real_event_{suffix}");
            let ev = json!({
                "tenant_id": "t",
                "entity_id": "e",
                "event_type": et,
                "payload": {}
            });
            prop_assert!(validate_evaluate_shape(&ev).is_err());
        }
    }
}

#[tokio::main]
async fn main() -> Result<()> {
    tracing_subscriber::fmt::init();
    dotenvy::dotenv().ok();

    let nats_url = env::var("NATS_URL").unwrap_or_else(|_| "nats://localhost:4222".to_string());
    let decision_api_url =
        env::var("DECISION_API_URL").unwrap_or_else(|_| "http://localhost:8000".to_string());
    let stream_name = env::var("STREAM_NAME").unwrap_or_else(|_| "FRAUD_EVENTS".to_string());
    let subject_prefix = env::var("SUBJECT_PREFIX").unwrap_or_else(|_| "fraud.events".to_string());
    let envelope_mode = env::var("INGEST_ENVELOPE_MODE").unwrap_or_else(|_| "optional".to_string());
    let require_idempotency_key = env::var("INGEST_REQUIRE_IDEMPOTENCY_KEY")
        .unwrap_or_default()
        .to_lowercase()
        .chars()
        .any(|c| matches!(c, '1' | 't' | 'y'));

    let upstream_api_key = env::var("UPSTREAM_API_KEY")
        .ok()
        .filter(|s| !s.trim().is_empty())
        .or_else(|| {
            env::var("API_KEYS")
                .ok()
                .and_then(|raw| raw.split(',').map(|s| s.trim().to_string()).find(|s| !s.is_empty()))
        });

    let dlq_subject = env::var("INGEST_DLQ_SUBJECT").unwrap_or_else(|_| "fraud.events.dlq".to_string());
    let deadletter_subject = env::var("INGEST_DEADLETTER_SUBJECT")
        .ok()
        .map(|s| s.trim().to_string())
        .filter(|s| !s.is_empty())
        .or_else(|| Some(format!("{}.deadletter", subject_prefix)));
    let pii_tokenize = env::var("INGEST_PII_TOKENIZE")
        .unwrap_or_default()
        .to_lowercase()
        .chars()
        .any(|c| matches!(c, '1' | 't' | 'y'));

    let nats_ready = Arc::new(AtomicBool::new(false));

    info!("Connecting to NATS at {}", nats_url);
    let client = async_nats::connect(&nats_url).await?;
    let js = jetstream::new(client);
    js.get_or_create_stream(StreamConfig {
        name: stream_name.clone(),
        subjects: vec![format!("{}.>", subject_prefix)],
        ..Default::default()
    })
    .await?;
    info!("Stream {} ready (subjects {}.>)", stream_name, subject_prefix);
    nats_ready.store(true, Ordering::Relaxed);

    let http = Client::builder()
        .timeout(std::time::Duration::from_secs(60))
        .build()?;

    let st = Arc::new(AppState {
        js: js.clone(),
        stream_name: stream_name.clone(),
        subject_prefix: subject_prefix.clone(),
        decision_api_url: decision_api_url.clone(),
        http,
        upstream_api_key,
        envelope_mode,
        require_idempotency_key,
        nats_ready: Arc::clone(&nats_ready),
        dlq_subject,
        deadletter_subject,
        pii_tokenize,
    });

    let consumer_st = Arc::clone(&st);
    tokio::spawn(async move {
        if let Err(e) = evaluate_consumer_loop(consumer_st).await {
            error!("evaluate consumer exited: {}", e);
        }
    });

    let app = Router::new()
        .route("/v1/health", get(health_check))
        .route("/v1/ready", get(ready_check))
        .route("/v1/events", post(post_events))
        .route("/v1/events/batch", post(post_events_batch))
        .route("/v1/stream/info", get(stream_info))
        .with_state(st);

    let port = env::var("PORT").unwrap_or_else(|_| "8007".to_string());
    let addr: SocketAddr = format!("0.0.0.0:{}", port).parse()?;
    info!("Listening on {}", addr);
    let listener = tokio::net::TcpListener::bind(addr).await?;
    axum::serve(listener, app).await?;
    Ok(())
}
