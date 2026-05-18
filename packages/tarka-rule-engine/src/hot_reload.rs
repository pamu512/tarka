//! Zero-downtime in-memory rule swaps via ``tokio::sync::watch`` (Prompt 192).

use std::sync::Arc;
use std::sync::atomic::{AtomicU64, Ordering};

use tokio::sync::watch;

use crate::ruleset::RuleSet;

/// Shared handle to the active [`RuleSet`]; readers clone ``Arc`` from the watch channel.
#[derive(Clone)]
pub struct HotReloadRuleStore {
    tx: watch::Sender<Arc<RuleSet>>,
    next_version: Arc<AtomicU64>,
}

impl HotReloadRuleStore {
    pub fn new(initial: RuleSet) -> Self {
        let ver = initial.version();
        let (tx, _rx) = watch::channel(Arc::new(initial));
        Self {
            tx,
            next_version: Arc::new(AtomicU64::new(ver.saturating_add(1))),
        }
    }

    /// Subscribe for push notifications when the active ruleset changes.
    pub fn subscribe(&self) -> watch::Receiver<Arc<RuleSet>> {
        self.tx.subscribe()
    }

    /// Current ruleset snapshot (cheap ``Arc`` clone).
    pub fn snapshot(&self) -> Arc<RuleSet> {
        self.tx.borrow().clone()
    }

    /// Atomically publish a new ruleset to all subscribers (in-flight evaluations keep their pinned ``Arc``).
    pub fn reload(&self, ruleset: RuleSet) {
        let v = ruleset.version();
        if v >= self.next_version.load(Ordering::SeqCst) {
            self.next_version.store(v.saturating_add(1), Ordering::SeqCst);
        }
        let _ = self.tx.send_replace(Arc::new(ruleset));
    }

    pub fn reload_from_json(&self, rules: &[serde_json::Value], version: Option<u64>) {
        let v = version.unwrap_or_else(|| self.next_version.fetch_add(1, Ordering::SeqCst));
        self.reload(RuleSet::from_rules_json(rules, v));
    }

    pub fn active_version(&self) -> u64 {
        self.snapshot().version()
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[tokio::test]
    async fn watch_notifies_subscriber_on_reload() {
        let store = HotReloadRuleStore::new(RuleSet::empty());
        let mut rx = store.subscribe();
        let _initial = rx.borrow().clone();

        store.reload_from_json(
            &[json!({
                "id": "shadow_a",
                "metadata": {"is_shadow": true},
                "when": [{"op": "gte", "field": "amount", "value": 100}]
            })],
            None,
        );

        rx.changed().await.expect("watch send");
        assert_eq!(rx.borrow().rule_count(), 1);
        assert!(rx.borrow().version() > 0);
    }

    #[tokio::test]
    async fn in_flight_snapshot_unaffected_by_reload() {
        let store = HotReloadRuleStore::new(RuleSet::empty());
        let pinned = store.snapshot();
        assert_eq!(pinned.rule_count(), 0);

        store.reload_from_json(
            &[json!({
                "id": "shadow_b",
                "metadata": {"is_shadow": true},
                "when": [{"op": "gte", "field": "amount", "value": 1}]
            })],
            None,
        );

        assert_eq!(pinned.rule_count(), 0);
        assert_eq!(store.snapshot().rule_count(), 1);
    }
}
