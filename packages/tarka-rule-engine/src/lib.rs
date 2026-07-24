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
) -> Result<EvaluationResult, String> {
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
        let out = evaluate_rules_json(&rules, &features).expect("valid rules");
        assert!(!out.is_blocked);
        assert_eq!(out.shadow_results.get("shadow_high_amount"), Some(&true));
    }

    #[test]
    fn malformed_rules_reject_atomically() {
        let rules = vec![
            json!({
                "id": "ok",
                "when": [{ "op": "eq", "field": "a", "value": 1 }]
            }),
            json!({
                "id": "bad",
                "when": [],
                "when_ast": {"type": "condition", "op": "eq", "field": "a", "value": 1}
            }),
        ];
        let features = serde_json::Map::new();
        let err = evaluate_rules_json(&rules, &features).expect_err("must reject");
        assert!(err.contains("invalid_rule"));
        assert!(err.contains("bad"));
    }
}
