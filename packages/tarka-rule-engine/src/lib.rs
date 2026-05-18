//! JSON rule evaluation core + hot-reload orchestrator (Prompts 189–192).

mod json_ast;

pub mod hot_reload;
#[cfg(feature = "hot-reload")]
pub mod nats_watcher;
pub mod ruleset;

pub use ruleset::{EvaluationResult, RuleSet};

pub fn evaluate_rules_json(
    rules: &[serde_json::Value],
    features: &serde_json::Map<String, serde_json::Value>,
) -> EvaluationResult {
    ruleset::evaluate_rules_json(rules, features)
}

#[cfg(feature = "python")]
mod python;

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn shadow_rule_match_does_not_block() {
        let rules = vec![json!({
            "id": "shadow_high_amount",
            "metadata": { "is_shadow": true },
            "when": [{ "op": "gte", "field": "amount", "value": 5000 }]
        })];
        let mut features = serde_json::Map::new();
        features.insert("amount".to_string(), json!(9000));
        let out = evaluate_rules_json(&rules, &features);
        assert!(!out.is_blocked);
        assert_eq!(out.shadow_results.get("shadow_high_amount"), Some(&true));
    }
}
