//! In-memory JSON rule set for observation (shadow) and blocking evaluation.

use std::collections::HashMap;
use std::sync::Arc;

use regex::Regex;
use serde::Serialize;
use serde_json::{Map, Value};

use crate::json_ast;

pub const MAX_FIELD_LEN: usize = 128;
pub const MAX_VALUE_LEN: usize = 1024;
pub const MAX_CONDITIONS_PER_RULE: usize = 20;

/// Outcome of evaluating a ruleset with observation (shadow) rules separated from blocking.
#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct EvaluationResult {
    pub is_blocked: bool,
    pub shadow_results: HashMap<String, bool>,
}

#[derive(Clone)]
pub(crate) struct Condition {
    pub op: String,
    pub field: String,
    pub value: Value,
    pub regex_compiled: Option<Arc<Regex>>,
}

#[derive(Clone)]
enum RulePredicate {
    Flat(Vec<Condition>),
    Ast(json_ast::AstNode),
}

#[derive(Clone)]
struct ParsedRule {
    id: String,
    is_shadow: bool,
    predicate: RulePredicate,
}

/// Versioned, hot-swappable rule bundle (Prompt 192).
#[derive(Clone)]
pub struct RuleSet {
    version: u64,
    rules: Arc<Vec<ParsedRule>>,
}

impl RuleSet {
    pub fn empty() -> Self {
        Self {
            version: 0,
            rules: Arc::new(Vec::new()),
        }
    }

    pub fn version(&self) -> u64 {
        self.version
    }

    pub fn rule_count(&self) -> usize {
        self.rules.len()
    }

    pub fn from_rules_json(rules: &[Value], version: u64) -> Self {
        let parsed: Vec<ParsedRule> = rules.iter().filter_map(parse_rule).collect();
        Self {
            version,
            rules: Arc::new(parsed),
        }
    }

    pub fn from_rules_blob(blob: &[u8], version: u64) -> Result<Self, serde_json::Error> {
        let v: Value = serde_json::from_slice(blob)?;
        let rules = match v {
            Value::Array(arr) => arr,
            Value::Object(mut obj) => obj
                .remove("rules")
                .and_then(|r| r.as_array().cloned())
                .unwrap_or_default(),
            _ => Vec::new(),
        };
        Ok(Self::from_rules_json(&rules, version))
    }

    pub fn evaluate(&self, features: &Map<String, Value>) -> EvaluationResult {
        evaluate_rules(self.rules.as_ref(), features)
    }
}

pub fn evaluate_rules_json(rules: &[Value], features: &Map<String, Value>) -> EvaluationResult {
    let parsed: Vec<ParsedRule> = rules.iter().filter_map(parse_rule).collect();
    evaluate_rules(&parsed, features)
}

pub(crate) fn match_condition(features: &Map<String, Value>, condition: &Condition) -> bool {
    let op = condition.op.as_str();
    let key = &condition.field;
    if key.is_empty() || key.len() > MAX_FIELD_LEN {
        return false;
    }
    let actual = features.get(key);
    let expected = &condition.value;
    if !expected.is_null() && format!("{expected}").len() > MAX_VALUE_LEN {
        return false;
    }
    match op {
        "eq" => actual == Some(expected),
        "not_eq" => actual != Some(expected),
        "gte" => actual
            .and_then(json_f64)
            .zip(json_f64(expected))
            .is_some_and(|(a, e)| a >= e),
        "gt" => actual
            .and_then(json_f64)
            .zip(json_f64(expected))
            .is_some_and(|(a, e)| a > e),
        "lte" => actual
            .and_then(json_f64)
            .zip(json_f64(expected))
            .is_some_and(|(a, e)| a <= e),
        "lt" => actual
            .and_then(json_f64)
            .zip(json_f64(expected))
            .is_some_and(|(a, e)| a < e),
        "in" => expected
            .as_array()
            .is_some_and(|arr| arr.iter().any(|v| Some(v) == actual)),
        "not_in" => match expected.as_array() {
            Some(arr) => !arr.iter().any(|v| Some(v) == actual),
            None => true,
        },
        "contains" => {
            let exp = json_str_pythonish(expected);
            let act = json_str_pythonish(&actual.cloned().unwrap_or(Value::Null));
            !exp.is_empty() && act.contains(&exp)
        }
        "starts_with" => {
            let suf = expected.as_str().unwrap_or("");
            actual
                .and_then(|a| a.as_str())
                .is_some_and(|a| a.starts_with(suf))
        }
        "ends_with" => {
            let suf = expected.as_str().unwrap_or("");
            actual
                .and_then(|a| a.as_str())
                .is_some_and(|a| a.ends_with(suf))
        }
        "regex" => {
            let act = format!("{}", actual.cloned().unwrap_or(Value::Null));
            condition
                .regex_compiled
                .as_ref()
                .is_some_and(|re| re.is_match(&act))
        }
        "is_true" => actual == Some(&Value::Bool(true)),
        "is_false" => actual == Some(&Value::Bool(false)),
        "exists" => actual.is_some(),
        "not_exists" => actual.is_none(),
        _ => false,
    }
}

fn json_f64(v: &Value) -> Option<f64> {
    v.as_f64()
        .or_else(|| v.as_i64().map(|i| i as f64))
        .or_else(|| v.as_u64().map(|u| u as f64))
}

fn json_str_pythonish(v: &Value) -> String {
    match v {
        Value::String(s) => s.clone(),
        Value::Bool(b) => b.to_string(),
        Value::Number(n) => n.to_string(),
        Value::Null => "None".to_string(),
        _ => v.to_string(),
    }
}

fn rule_is_shadow(rule: &Value) -> bool {
    rule.get("metadata")
        .and_then(|m| m.get("is_shadow"))
        .and_then(|v| v.as_bool())
        .unwrap_or(false)
}

fn build_safe_regex_pattern(pattern: &str) -> String {
    let escaped = regex::escape(pattern);
    format!("(?i)^{}$", escaped.replace(r"\*", ".*").replace(r"\?", "."))
}

fn parse_flat_when(rule: &Value, _rid: &str) -> Option<Vec<Condition>> {
    let when = rule.get("when")?.as_array()?;
    if when.is_empty() || when.len() > MAX_CONDITIONS_PER_RULE {
        return None;
    }
    let mut conds = Vec::new();
    for c in when {
        let op = c
            .get("op")
            .and_then(|x| x.as_str())
            .unwrap_or("eq")
            .to_string();
        let field = c.get("field").and_then(|x| x.as_str()).unwrap_or("").to_string();
        if field.is_empty() || field.len() > MAX_FIELD_LEN {
            return None;
        }
        let value = c.get("value").cloned().unwrap_or(Value::Null);
        let regex_compiled = if op == "regex" {
            let pat = value.as_str()?;
            if pat.is_empty() || pat.len() > json_ast::MAX_REGEX_PATTERN_LEN {
                return None;
            }
            let safe = build_safe_regex_pattern(pat);
            Some(Arc::new(Regex::new(&safe).ok()?))
        } else {
            None
        };
        conds.push(Condition {
            op,
            field,
            value,
            regex_compiled,
        });
    }
    Some(conds)
}

fn parse_rule(rule: &Value) -> Option<ParsedRule> {
    let rid = rule
        .get("id")
        .and_then(|x| x.as_str())
        .unwrap_or("unknown")
        .to_string();
    let has_flat = rule
        .get("when")
        .and_then(|x| x.as_array())
        .is_some_and(|w| !w.is_empty());
    let has_ast = rule
        .get("when_ast")
        .map(|v| !v.is_null())
        .unwrap_or(false);
    if has_flat && has_ast {
        return None;
    }
    let is_shadow = rule_is_shadow(rule);
    if has_ast {
        let raw = rule.get("when_ast")?;
        let ast = json_ast::parse_ast_strict_in_rule(raw, "when_ast", rid.as_str()).ok()?;
        return Some(ParsedRule {
            id: rid,
            is_shadow,
            predicate: RulePredicate::Ast(ast),
        });
    }
    let when = parse_flat_when(rule, rid.as_str())?;
    Some(ParsedRule {
        id: rid,
        is_shadow,
        predicate: RulePredicate::Flat(when),
    })
}

fn rule_matches(rule: &ParsedRule, features: &Map<String, Value>) -> bool {
    match &rule.predicate {
        RulePredicate::Ast(ast) => json_ast::eval_ast(ast, features),
        RulePredicate::Flat(conds) => {
            !conds.is_empty() && conds.iter().all(|c| match_condition(features, c))
        }
    }
}

fn evaluate_rules(rules: &[ParsedRule], features: &Map<String, Value>) -> EvaluationResult {
    let mut is_blocked = false;
    let mut shadow_results = HashMap::new();
    for rule in rules {
        let matched = rule_matches(rule, features);
        if rule.is_shadow {
            shadow_results.insert(rule.id.clone(), matched);
        } else if matched {
            is_blocked = true;
        }
    }
    EvaluationResult {
        is_blocked,
        shadow_results,
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn ruleset_version_bumps_on_reload_shape() {
        let rs = RuleSet::from_rules_json(
            &[json!({
                "id": "r1",
                "metadata": {"is_shadow": true},
                "when": [{"op": "gte", "field": "amount", "value": 1}]
            })],
            3,
        );
        assert_eq!(rs.version(), 3);
        assert_eq!(rs.rule_count(), 1);
    }
}
