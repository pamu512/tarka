//! Hot-reload orchestrator: NATS hypothesis deploy → in-memory [`RuleSet`] via ``watch`` channel.

use std::sync::Arc;

use tarka_rule_engine::hot_reload::HotReloadRuleStore;
use tarka_rule_engine::nats_watcher::{load_initial_ruleset_from_redis, NatsWatcherConfig};
use tarka_rule_engine::ruleset::RuleSet;
use tracing_subscriber::EnvFilter;

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error + Send + Sync>> {
    tracing_subscriber::fmt()
        .with_env_filter(
            EnvFilter::try_from_default_env()
                .unwrap_or_else(|_| EnvFilter::new("info,tarka_rule_engine=debug")),
        )
        .init();

    let config = NatsWatcherConfig::from_env()?;

    let initial = if let Some(ref redis_url) = config.redis_url {
        load_initial_ruleset_from_redis(redis_url, &config.redis_key)
            .await
            .unwrap_or_else(|e| {
                tracing::warn!(error = %e, "initial_redis_ruleset_load_failed_using_empty");
                RuleSet::empty()
            })
    } else {
        RuleSet::empty()
    };

    let store = Arc::new(HotReloadRuleStore::new(initial));
    tracing::info!(
        version = store.active_version(),
        rule_count = store.snapshot().rule_count(),
        "hot_reload_store_ready"
    );

    tarka_rule_engine::nats_watcher::run_hypothesis_deploy_watcher(store, config)
        .await?;
    Ok(())
}
