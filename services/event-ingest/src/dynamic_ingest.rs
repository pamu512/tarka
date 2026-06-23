//! Schemaless ingest: fingerprint payloads, apply cached/heuristic maps, DLQ + async mapping requests.
//!
//! Compliance: callers must tokenize PII **before** any sample is sent to an external LLM worker
//! (the mapping-request payload is tokenized in the HTTP handler).

use anyhow::Result;
use async_nats::jetstream::{self, stream::Config as StreamConfig};
use dashmap::DashMap;
use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use std::collections::BTreeSet;
use std::sync::Arc;
use redis::AsyncCommands;
use tracing::{info, warn};

const INGEST_MISC_STREAM: &str = "FRAUD_INGEST_MISC";

/// Stable fingerprint of top-level keys (tenant-scoped mapping cache key part).
pub fn schema_fingerprint(body: &Value) -> String {
    let keys: BTreeSet<String> = body
        .as_object()
        .map(|o| o.keys().cloned().collect())
        .unwrap_or_default();
    let joined = keys.into_iter().collect::<Vec<_>>().join(",");
    format!("{:x}", Sha256::digest(joined.as_bytes()))
}

fn cache_key(tenant_id: &str, fp: &str) -> String {
    format!("{tenant_id}:{fp}")
}

/// Heuristic map arbitrary JSON into evaluate_request shape when common aliases exist.
pub fn heuristic_map_to_evaluate_request(body: &Value) -> Option<Value> {
    let obj = body.as_object()?;
    let tenant = obj
        .get("tenant_id")
        .or_else(|| obj.get("tenantId"))
        .and_then(|v| v.as_str())
        .map(str::trim)
        .filter(|s| !s.is_empty())?;
    let entity = obj
        .get("entity_id")
        .or_else(|| obj.get("entityId"))
        .or_else(|| obj.get("user_id"))
        .or_else(|| obj.get("userId"))
        .or_else(|| obj.get("customer_id"))
        .or_else(|| obj.get("customerId"))
        .and_then(|v| v.as_str())
        .map(str::trim)
        .filter(|s| !s.is_empty())?;
    let et = obj
        .get("event_type")
        .or_else(|| obj.get("eventType"))
        .or_else(|| obj.get("type"))
        .and_then(|v| v.as_str())
        .map(str::trim)
        .filter(|s| !s.is_empty())?;
    let payload = obj
        .get("payload")
        .cloned()
        .or_else(|| {
            let mut m = serde_json::Map::new();
            for (k, v) in obj {
                if matches!(
                    k.as_str(),
                    "tenant_id"
                        | "tenantId"
                        | "entity_id"
                        | "entityId"
                        | "user_id"
                        | "userId"
                        | "customer_id"
                        | "customerId"
                        | "event_type"
                        | "eventType"
                        | "type"
                        | "metadata"
                ) {
                    continue;
                }
                m.insert(k.clone(), v.clone());
            }
            if m.is_empty() {
                None
            } else {
                Some(Value::Object(m))
            }
        })
        .unwrap_or_else(|| json!({}));
    let metadata = obj.get("metadata").cloned().unwrap_or_else(|| json!({}));
    Some(json!({
        "tenant_id": tenant,
        "entity_id": entity,
        "event_type": et,
        "payload": payload,
        "metadata": metadata
    }))
}

#[derive(Clone)]
pub struct DynamicIngestState {
    /// Serialized mapping JSON: same shape as heuristic output OR jsonpath rules extension.
    cache: Arc<DashMap<String, Value>>,
}

impl DynamicIngestState {
    pub fn new() -> Self {
        Self {
            cache: Arc::new(DashMap::new()),
        }
    }
}

pub async fn ensure_ingest_misc_stream(js: &jetstream::Context) -> Result<()> {
    js.get_or_create_stream(StreamConfig {
        name: INGEST_MISC_STREAM.to_string(),
        subjects: vec![
            "fraud.ingest.dlq".into(),
            "fraud.ingest.mapping.request".into(),
        ],
        ..Default::default()
    })
    .await?;
    Ok(())
}

pub async fn publish_ingest_dlq(
    js: &jetstream::Context,
    record: Value,
) -> Result<()> {
    js.publish("fraud.ingest.dlq".to_string(), serde_json::to_vec(&record)?.into())
        .await?
        .await?;
    Ok(())
}

pub async fn publish_mapping_request(
    js: &jetstream::Context,
    record: Value,
) -> Result<()> {
    js.publish(
        "fraud.ingest.mapping.request".to_string(),
        serde_json::to_vec(&record)?.into(),
    )
    .await?
    .await?;
    Ok(())
}

/// Apply a cached mapping object. Supports either a full evaluate_request in `evaluate_request`
/// or a list of field copies in `field_map`: [{ "from": "$.userId", "to": "entity_id" }, ...] (subset implemented: flat keys).
pub fn apply_cached_mapping(body: &Value, mapping: &Value) -> Option<Value> {
    if let Some(ev) = mapping.get("evaluate_request").cloned() {
        return Some(ev);
    }
    if let Some(arr) = mapping.get("field_map").and_then(|x| x.as_array()) {
        let mut base = body.as_object()?.clone();
        for rule in arr {
            let from = rule.get("from")?.as_str()?;
            let to = rule.get("to")?.as_str()?;
            let key = from.strip_prefix("$.").unwrap_or(from);
            if let Some(v) = body.get(key).cloned() {
                base.insert(to.to_string(), v);
            }
        }
        return heuristic_map_to_evaluate_request(&Value::Object(base));
    }
    None
}

pub fn spawn_mapping_request(
    js: jetstream::Context,
    pii_safe_sample: Value,
    tenant_id: String,
    fingerprint: String,
) {
    tokio::spawn(async move {
        if let Err(e) = publish_mapping_request(&js, pii_safe_sample).await {
            warn!("mapping request publish failed: {}", e);
        } else {
            info!(
                "published ingest mapping request tenant={} fp={}",
                tenant_id, fingerprint
            );
        }
    });
}

/// L1 DashMap + optional L2 Redis (`ingest:map:{tenant}:{fingerprint}` JSON).
pub async fn mapping_cache_lookup(
    redis: &Option<redis::aio::ConnectionManager>,
    local: &DynamicIngestState,
    tenant_id: &str,
    fp: &str,
) -> Option<Value> {
    let k = cache_key(tenant_id, fp);
    if let Some(v) = local.cache.get(&k) {
        return Some(v.clone());
    }
    if let Some(conn) = redis {
        let key = format!("ingest:map:{k}");
        if let Ok(Some(s)) = conn.clone().get::<_, Option<String>>(key).await {
            if let Ok(v) = serde_json::from_str::<Value>(&s) {
                local.cache.insert(k, v.clone());
                return Some(v);
            }
        }
    }
    None
}

pub async fn mapping_cache_store(
    redis: &Option<redis::aio::ConnectionManager>,
    local: &DynamicIngestState,
    tenant_id: &str,
    fp: &str,
    mapping: Value,
) -> Result<()> {
    let k = cache_key(tenant_id, fp);
    local.cache.insert(k.clone(), mapping.clone());
    if let Some(conn) = redis {
        let key = format!("ingest:map:{k}");
        let s = serde_json::to_string(&mapping)?;
        let _: () = conn.clone().set(key, s).await?;
    }
    Ok(())
}
