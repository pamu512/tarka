//! Best-effort [`tarka_core::engine::MockExternal`] reconstruction from captured trace steps.

use std::collections::{BTreeMap, HashMap, HashSet};

use serde::Deserialize;
use tarka_core::engine::MockExternal;

#[derive(Debug, Deserialize)]
pub struct TraceStepJson {
    pub rule_id: String,
    pub logic_operator: String,
    pub operands: Vec<String>,
    pub result: bool,
    #[serde(default)]
    pub state_snapshot: BTreeMap<String, String>,
    #[serde(default)]
    pub otel_trace_id: String,
}

pub fn mock_external_from_steps(steps: &[TraceStepJson]) -> MockExternal {
    let mut redis: HashMap<String, String> = HashMap::new();
    let mut list_positive: HashMap<String, HashSet<String>> = HashMap::new();
    let mut customs: HashMap<String, bool> = HashMap::new();

    for step in steps {
        match step.logic_operator.as_str() {
            "REDIS" => {
                let Some(key) = step.operands.first() else {
                    continue;
                };
                if let Some(raw) = step.state_snapshot.get("redis.value.raw") {
                    redis.insert(key.clone(), raw.clone());
                }
            }
            "LIST" => {
                let list_name = step
                    .state_snapshot
                    .get("list.name")
                    .cloned()
                    .or_else(|| step.operands.first().cloned())
                    .unwrap_or_default();
                if list_name.is_empty() {
                    continue;
                }
                let item = step
                    .state_snapshot
                    .get("list.item.resolved")
                    .cloned()
                    .unwrap_or_default();
                let contains = step
                    .state_snapshot
                    .get("list.lookup.contains")
                    .map(|s| s == "true")
                    .unwrap_or(step.result);
                let bucket = list_positive.entry(list_name).or_default();
                if contains && !item.is_empty() {
                    bucket.insert(item);
                }
            }
            "CUSTOM" => {
                let name = step
                    .state_snapshot
                    .get("custom.name")
                    .cloned()
                    .unwrap_or_else(|| step.rule_id.clone());
                let outcome = step
                    .state_snapshot
                    .get("custom.result")
                    .map(|s| s == "true")
                    .unwrap_or(step.result);
                customs.insert(name, outcome);
            }
            _ => {}
        }
    }

    let lists: HashMap<String, Vec<String>> = list_positive
        .into_iter()
        .map(|(k, set)| (k, set.into_iter().collect()))
        .collect();

    MockExternal {
        redis,
        lists,
        customs,
    }
}
