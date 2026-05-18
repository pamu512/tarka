//! NATS listener: reload [`RuleSet`] on ``hypothesis_deployed`` API events (Prompt 192).

use std::sync::Arc;

use futures_util::StreamExt;
use serde::Deserialize;
use serde_json::Value;
use tracing::{error, info, warn};

use crate::hot_reload::HotReloadRuleStore;
use crate::ruleset::RuleSet;

pub const DEFAULT_HYPOTHESIS_DEPLOY_SUBJECT: &str = "tarka.hypothesis.deployed";
pub const DEFAULT_SHADOW_RULES_REDIS_KEY: &str = "shadow:rules:active";

#[derive(Debug, Clone, Deserialize)]
pub struct HypothesisDeployEvent {
    pub event: String,
    #[serde(default)]
    pub version: Option<u64>,
    #[serde(default)]
    pub tenant_id: Option<String>,
    /// Inline rules payload (preferred when API publishes full bundle).
    #[serde(default)]
    pub rules: Option<Vec<Value>>,
    /// Redis key holding the active shadow rule list (fallback).
    #[serde(default)]
    pub redis_key: Option<String>,
}

impl HypothesisDeployEvent {
    pub fn is_deploy(&self) -> bool {
        self.event == "hypothesis_deployed" || self.event == "hypothesis.deployed"
    }
}

#[derive(Debug, Clone)]
pub struct NatsWatcherConfig {
    pub nats_url: String,
    pub subject: String,
    pub redis_url: Option<String>,
    pub redis_key: String,
}

impl NatsWatcherConfig {
    pub fn from_env() -> Result<Self, String> {
        let nats_url = std::env::var("RULE_ENGINE_NATS_URL")
            .or_else(|_| std::env::var("NATS_URL"))
            .map_err(|_| "RULE_ENGINE_NATS_URL or NATS_URL is required".to_string())?;
        let subject = std::env::var("RULE_ENGINE_HYPOTHESIS_DEPLOY_SUBJECT")
            .unwrap_or_else(|_| DEFAULT_HYPOTHESIS_DEPLOY_SUBJECT.to_string());
        let redis_url = std::env::var("SHADOW_RULES_REDIS_URL")
            .or_else(|_| std::env::var("REDIS_URL"))
            .ok()
            .filter(|s| !s.trim().is_empty());
        let redis_key = std::env::var("SHADOW_RULES_ACTIVE_KEY")
            .unwrap_or_else(|_| DEFAULT_SHADOW_RULES_REDIS_KEY.to_string());
        Ok(Self {
            nats_url,
            subject,
            redis_url,
            redis_key,
        })
    }
}

pub async fn load_initial_ruleset_from_redis(
    redis_url: &str,
    redis_key: &str,
) -> Result<RuleSet, String> {
    let client = redis::Client::open(redis_url).map_err(|e| e.to_string())?;
    let mut conn = client
        .get_multiplexed_async_connection()
        .await
        .map_err(|e| e.to_string())?;
    let raw: Option<String> = redis::cmd("GET")
        .arg(redis_key)
        .query_async(&mut conn)
        .await
        .map_err(|e| e.to_string())?;
    let Some(blob) = raw else {
        return Ok(RuleSet::empty());
    };
    let v: Value = serde_json::from_str(&blob).map_err(|e| e.to_string())?;
    let rules = flatten_rules_blob(&v);
    Ok(RuleSet::from_rules_json(&rules, 1))
}

fn flatten_rules_blob(v: &Value) -> Vec<Value> {
    match v {
        Value::Array(items) => {
            let mut out = Vec::new();
            for item in items {
                if let Some(rules) = item.get("rules").and_then(|r| r.as_array()) {
                    if item.get("mode").and_then(|m| m.as_str()) != Some("disabled") {
                        out.extend(rules.iter().cloned());
                    }
                } else {
                    out.push(item.clone());
                }
            }
            out
        }
        _ => Vec::new(),
    }
}

async fn resolve_rules_for_event(
    event: &HypothesisDeployEvent,
    config: &NatsWatcherConfig,
) -> Result<Vec<Value>, String> {
    if let Some(rules) = &event.rules {
        if !rules.is_empty() {
            return Ok(rules.clone());
        }
    }
    let redis_url = config
        .redis_url
        .as_deref()
        .ok_or_else(|| "redis_url not configured and event.rules empty".to_string())?;
    let key = event
        .redis_key
        .as_deref()
        .unwrap_or(config.redis_key.as_str());
    let client = redis::Client::open(redis_url).map_err(|e| e.to_string())?;
    let mut conn = client
        .get_multiplexed_async_connection()
        .await
        .map_err(|e| e.to_string())?;
    let raw: Option<String> = redis::cmd("GET")
        .arg(key)
        .query_async(&mut conn)
        .await
        .map_err(|e| e.to_string())?;
    let Some(blob) = raw else {
        return Ok(Vec::new());
    };
    let v: Value = serde_json::from_str(&blob).map_err(|e| e.to_string())?;
    Ok(flatten_rules_blob(&v))
}

pub async fn apply_hypothesis_deploy_event(
    store: &HotReloadRuleStore,
    event: &HypothesisDeployEvent,
    config: &NatsWatcherConfig,
) -> Result<(), String> {
    if !event.is_deploy() {
        return Ok(());
    }
    let rules = resolve_rules_for_event(event, config).await?;
    let version = event.version.unwrap_or_else(|| store.active_version() + 1);
    store.reload(RuleSet::from_rules_json(&rules, version));
    info!(
        target: "tarka_rule_engine.hot_reload",
        version = version,
        rule_count = rules.len(),
        tenant_id = ?event.tenant_id,
        "hypothesis_ruleset_reloaded"
    );
    Ok(())
}

/// Long-lived NATS subscription; reloads the shared store without dropping the TCP connection.
pub async fn run_hypothesis_deploy_watcher(
    store: Arc<HotReloadRuleStore>,
    config: NatsWatcherConfig,
) -> Result<(), String> {
    let client = async_nats::connect(&config.nats_url)
        .await
        .map_err(|e| format!("nats connect: {e}"))?;
    let mut subscriber = client
        .subscribe(config.subject.clone())
        .await
        .map_err(|e| format!("nats subscribe {}: {e}", config.subject))?;

    info!(
        target: "tarka_rule_engine.hot_reload",
        subject = %config.subject,
        "hypothesis_deploy_watcher_started"
    );

    while let Some(msg) = subscriber.next().await {
        let payload = msg.payload;
        let event: HypothesisDeployEvent = match serde_json::from_slice(&payload) {
            Ok(e) => e,
            Err(e) => {
                warn!(
                    target: "tarka_rule_engine.hot_reload",
                    error = %e,
                    "hypothesis_deploy_invalid_json"
                );
                continue;
            }
        };
        if let Err(e) = apply_hypothesis_deploy_event(store.as_ref(), &event, &config).await {
            error!(
                target: "tarka_rule_engine.hot_reload",
                error = %e,
                "hypothesis_deploy_reload_failed"
            );
        }
    }
    Ok(())
}

#[cfg(all(test, feature = "hot-reload"))]
mod tests {
    use super::*;
    use crate::hot_reload::HotReloadRuleStore;
    use crate::ruleset::RuleSet;
    use serde_json::json;

    #[tokio::test]
    async fn deploy_event_reloads_ruleset_in_watch_store() {
        let store = HotReloadRuleStore::new(RuleSet::empty());
        let event = HypothesisDeployEvent {
            event: "hypothesis_deployed".to_string(),
            version: Some(42),
            tenant_id: Some("demo".to_string()),
            rules: Some(vec![json!({
                "id": "shadow_lane",
                "metadata": {"is_shadow": true},
                "when": [{"op": "contains", "field": "lane", "value": "STRESS"}]
            })]),
            redis_key: None,
        };
        let config = NatsWatcherConfig {
            nats_url: "nats://unused".to_string(),
            subject: DEFAULT_HYPOTHESIS_DEPLOY_SUBJECT.to_string(),
            redis_url: None,
            redis_key: DEFAULT_SHADOW_RULES_REDIS_KEY.to_string(),
        };
        apply_hypothesis_deploy_event(&store, &event, &config)
            .await
            .expect("apply");
        assert_eq!(store.snapshot().version(), 42);
        assert_eq!(store.snapshot().rule_count(), 1);
    }
}
