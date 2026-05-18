//! Parse YAML rule definitions with [`serde_yaml`] and emit [`super::RuleSet`] protobuf messages.

use std::collections::HashSet;

use serde::Deserialize;

use super::error::CompileError;
use super::locate::line_for_signal_assignment;
use super::registry::SignalRegistry;
use super::signal_type::SignalType;
use super::type_check::type_check_expr;
use super::{
    rule_expression, scalar_value, AndExpr, CompiledRule, NotExpr, OrExpr, RuleExpression,
    RuleSet, ScalarValue, SignalCompareLeaf,
};

/// Maximum nesting depth for `and` / `or` / `not` (prevents hostile YAML stacks).
pub const MAX_RULE_TREE_DEPTH: usize = 96;
/// Maximum expression nodes (composite + leaves) per compiled rule set.
pub const MAX_RULE_TREE_NODES: usize = 4096;

const ALLOWED_OPS: &[&str] = &[
    "eq",
    "ne",
    "lt",
    "lte",
    "gt",
    "gte",
    "string_contains",
];

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct YamlRuleSetInput {
    version: u32,
    rules: Vec<YamlRuleInput>,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct YamlRuleInput {
    id: String,
    expression: YamlExpr,
}

#[derive(Debug, Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case", deny_unknown_fields)]
pub enum YamlExpr {
    And {
        children: Vec<YamlExpr>,
    },
    Or {
        children: Vec<YamlExpr>,
    },
    Not {
        child: Box<YamlExpr>,
    },
    CompareSignal {
        signal_name: String,
        op: String,
        expected: serde_yaml::Value,
    },
}

/// Parse YAML and compile to [`RuleSet`], validating every `signal_name` against `registry`.
pub fn compile_yaml_rule_set(yaml_source: &str, registry: &SignalRegistry) -> Result<RuleSet, CompileError> {
    let parsed: YamlRuleSetInput =
        serde_yaml::from_str(yaml_source).map_err(|e| yaml_parse_err(&e))?;

    validate_rule_ids(&parsed.rules)?;

    let mut total_nodes = 0usize;
    for r in &parsed.rules {
        let d = expr_depth(&r.expression);
        if d > MAX_RULE_TREE_DEPTH {
            return Err(CompileError::validation(
                format!(
                    "rule `{}` exceeds maximum expression depth ({MAX_RULE_TREE_DEPTH})",
                    r.id
                ),
                None,
            ));
        }
        let n = count_nodes(&r.expression);
        total_nodes = total_nodes.saturating_add(n);
        if total_nodes > MAX_RULE_TREE_NODES {
            return Err(CompileError::validation(
                format!("rule set exceeds maximum expression node budget ({MAX_RULE_TREE_NODES})"),
                None,
            ));
        }
    }

    for rule in &parsed.rules {
        let sigs = collect_signal_names_in_order(&rule.expression);
        for name in sigs {
            if registry.contains(&name) {
                continue;
            }
            let line = line_for_signal_assignment(yaml_source, &name);
            let sug = closest_registry_match(&name, registry);
            return Err(CompileError::undefined_signal(name, line, sug.map(|s| s.to_string())));
        }
    }

    for rule in &parsed.rules {
        type_check_expr(&rule.expression, registry, yaml_source)?;
    }

    let mut rules_out = Vec::with_capacity(parsed.rules.len());
    for rule in parsed.rules {
        let expr = yaml_expr_to_proto(&rule.expression, registry)?;
        rules_out.push(CompiledRule {
            id: rule.id.trim().to_string(),
            expression: Some(expr),
        });
    }

    Ok(RuleSet {
        version: parsed.version,
        rules: rules_out,
    })
}

fn yaml_parse_err(e: &serde_yaml::Error) -> CompileError {
    let line = e.location().map(|loc| loc.line() as u32);
    CompileError::yaml_parse(format!("YAML parse error: {e}"), line)
}

fn validate_rule_ids(rules: &[YamlRuleInput]) -> Result<(), CompileError> {
    let mut seen = HashSet::new();
    for r in rules {
        let canon = r.id.trim().to_string();
        if canon.is_empty() {
            return Err(CompileError::validation(
                "every rule must have a non-empty `id`",
                None,
            ));
        }
        if !seen.insert(canon.clone()) {
            return Err(CompileError::validation(
                format!("duplicate rule id `{canon}`"),
                None,
            ));
        }
    }
    Ok(())
}

fn expr_depth(e: &YamlExpr) -> usize {
    match e {
        YamlExpr::And { children } | YamlExpr::Or { children } => {
            1 + children.iter().map(expr_depth).max().unwrap_or(0)
        }
        YamlExpr::Not { child } => 1 + expr_depth(child),
        YamlExpr::CompareSignal { .. } => 1,
    }
}

fn count_nodes(e: &YamlExpr) -> usize {
    match e {
        YamlExpr::And { children } | YamlExpr::Or { children } => {
            1 + children.iter().map(count_nodes).sum::<usize>()
        }
        YamlExpr::Not { child } => 1 + count_nodes(child),
        YamlExpr::CompareSignal { .. } => 1,
    }
}

fn collect_signal_names_in_order(e: &YamlExpr) -> Vec<String> {
    let mut out = Vec::new();
    walk_collect(e, &mut out);
    out
}

fn walk_collect(e: &YamlExpr, out: &mut Vec<String>) {
    match e {
        YamlExpr::And { children } | YamlExpr::Or { children } => {
            for c in children {
                walk_collect(c, out);
            }
        }
        YamlExpr::Not { child } => walk_collect(child, out),
        YamlExpr::CompareSignal { signal_name, .. } => out.push(signal_name.trim().to_string()),
    }
}

fn yaml_expr_to_proto(e: &YamlExpr, registry: &SignalRegistry) -> Result<RuleExpression, CompileError> {
    match e {
        YamlExpr::And { children } => {
            if children.is_empty() {
                return Err(CompileError::validation(
                    "`kind: and` requires a non-empty `children` list",
                    None,
                ));
            }
            let mut ch = Vec::with_capacity(children.len());
            for c in children {
                ch.push(yaml_expr_to_proto(c, registry)?);
            }
            Ok(RuleExpression {
                expr: Some(rule_expression::Expr::And(AndExpr { children: ch })),
            })
        }
        YamlExpr::Or { children } => {
            if children.is_empty() {
                return Err(CompileError::validation(
                    "`kind: or` requires a non-empty `children` list",
                    None,
                ));
            }
            let mut ch = Vec::with_capacity(children.len());
            for c in children {
                ch.push(yaml_expr_to_proto(c, registry)?);
            }
            Ok(RuleExpression {
                expr: Some(rule_expression::Expr::Or(OrExpr { children: ch })),
            })
        }
        YamlExpr::Not { child } => Ok(RuleExpression {
            expr: Some(rule_expression::Expr::Not(Box::new(NotExpr {
                child: Some(Box::new(yaml_expr_to_proto(child, registry)?)),
            }))),
        }),
        YamlExpr::CompareSignal {
            signal_name,
            op,
            expected,
        } => {
            let op_norm = op.trim();
            if !ALLOWED_OPS.contains(&op_norm) {
                return Err(CompileError::validation(
                    format!(
                        "unsupported comparison op `{op_norm}` (allowed: {})",
                        ALLOWED_OPS.join(", ")
                    ),
                    None,
                ));
            }
            let sn = signal_name.trim();
            if sn.is_empty() {
                return Err(CompileError::validation(
                    "`signal_name` must be non-empty for compare_signal",
                    None,
                ));
            }
            let sty = registry.signal_type(sn).ok_or_else(|| {
                CompileError::validation(format!("unknown signal `{sn}`"), None)
            })?;
            let scalar = yaml_expected_to_scalar_for_signal(expected, sty)?;
            Ok(RuleExpression {
                expr: Some(rule_expression::Expr::CompareSignal(SignalCompareLeaf {
                    signal_name: sn.to_string(),
                    op: op_norm.to_string(),
                    expected: Some(scalar),
                })),
            })
        }
    }
}

/// Encode YAML `expected` into protobuf [`ScalarValue`] consistent with [`SignalType`].
fn yaml_expected_to_scalar_for_signal(
    v: &serde_yaml::Value,
    sty: SignalType,
) -> Result<ScalarValue, CompileError> {
    match sty {
        SignalType::Boolean => match v {
            serde_yaml::Value::Bool(b) => Ok(ScalarValue {
                value: Some(scalar_value::Value::BoolValue(*b)),
            }),
            _ => Err(CompileError::validation(
                "Boolean signal: `expected` must be a YAML boolean",
                None,
            )),
        },
        SignalType::Integer => match v {
            serde_yaml::Value::Number(n) => {
                if let Some(i) = n.as_i64() {
                    return Ok(ScalarValue {
                        value: Some(scalar_value::Value::IntValue(i)),
                    });
                }
                if let Some(u) = n.as_u64() {
                    if u <= i64::MAX as u64 {
                        return Ok(ScalarValue {
                            value: Some(scalar_value::Value::IntValue(u as i64)),
                        });
                    }
                }
                if yaml_number_is_integral(n) {
                    let f = n.as_f64().unwrap_or(0.0);
                    return Ok(ScalarValue {
                        value: Some(scalar_value::Value::IntValue(f as i64)),
                    });
                }
                Err(CompileError::validation(
                    "Integer signal: `expected` must be an integral YAML number",
                    None,
                ))
            }
            _ => Err(CompileError::validation(
                "Integer signal: `expected` must be a YAML number",
                None,
            )),
        },
        SignalType::Float => match v {
            serde_yaml::Value::Number(n) => {
                let f = n.as_f64().ok_or_else(|| {
                    CompileError::validation("Float signal: invalid YAML number", None)
                })?;
                Ok(ScalarValue {
                    value: Some(scalar_value::Value::DoubleValue(f)),
                })
            }
            _ => Err(CompileError::validation(
                "Float signal: `expected` must be a YAML number",
                None,
            )),
        },
        SignalType::String => match v {
            serde_yaml::Value::String(s) => Ok(ScalarValue {
                value: Some(scalar_value::Value::StringValue(s.clone())),
            }),
            _ => Err(CompileError::validation(
                "String signal: `expected` must be a YAML string",
                None,
            )),
        },
        SignalType::List => match v {
            serde_yaml::Value::Sequence(_) => {
                let json = serde_json::to_value(v).map_err(|e| {
                    CompileError::validation(format!("list `expected` JSON encode failed: {e}"), None)
                })?;
                let s = serde_json::to_string(&json).map_err(|e| {
                    CompileError::validation(format!("list `expected` stringify failed: {e}"), None)
                })?;
                Ok(ScalarValue {
                    value: Some(scalar_value::Value::StringValue(s)),
                })
            }
            serde_yaml::Value::String(s) => {
                let t = s.trim();
                let jv: serde_json::Value = serde_json::from_str(t).map_err(|e| {
                    CompileError::validation(
                        format!("List signal: string `expected` must be valid JSON: {e}"),
                        None,
                    )
                })?;
                if !jv.is_array() {
                    return Err(CompileError::validation(
                        "List signal: string `expected` must be a JSON array",
                        None,
                    ));
                }
                let normalized = serde_json::to_string(&jv).map_err(|e| {
                    CompileError::validation(
                        format!("List signal: could not normalize JSON array: {e}"),
                        None,
                    )
                })?;
                Ok(ScalarValue {
                    value: Some(scalar_value::Value::StringValue(normalized)),
                })
            }
            _ => Err(CompileError::validation(
                "List signal: `expected` must be a YAML sequence or JSON-array string",
                None,
            )),
        },
    }
}

fn yaml_number_is_integral(n: &serde_yaml::Number) -> bool {
    if n.as_i64().is_some() || n.as_u64().is_some() {
        return true;
    }
    n.as_f64()
        .map(|f| f.is_finite() && f.fract().abs() <= f64::EPSILON && f.abs() <= i64::MAX as f64)
        .unwrap_or(false)
}

/// Return the registry name with smallest Levenshtein distance when distance is within a threshold.
fn closest_registry_match<'a>(unknown: &str, registry: &'a SignalRegistry) -> Option<&'a str> {
    let threshold = (unknown.len() / 3).clamp(2, 12);
    let mut best: Option<(usize, &'a str)> = None;
    for name in registry.names() {
        let d = levenshtein(unknown, name);
        if best.as_ref().map_or(true, |(bd, _)| d < *bd) {
            best = Some((d, name));
        }
    }
    best.and_then(|(d, s)| (d <= threshold).then_some(s))
}

fn levenshtein(a: &str, b: &str) -> usize {
    let a: Vec<char> = a.chars().collect();
    let b: Vec<char> = b.chars().collect();
    let n = a.len();
    let m = b.len();
    if n == 0 {
        return m;
    }
    if m == 0 {
        return n;
    }
    let mut prev: Vec<usize> = (0..=m).collect();
    let mut curr = vec![0usize; m + 1];
    for i in 1..=n {
        curr[0] = i;
        for j in 1..=m {
            let cost = usize::from(a[i - 1] != b[j - 1]);
            curr[j] = (curr[j - 1] + 1)
                .min(prev[j] + 1)
                .min(prev[j - 1] + cost);
        }
        std::mem::swap(&mut prev, &mut curr);
    }
    prev[m]
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::compiler::SignalRegistry;

    const REG_JSON: &str = r#"{"signals":{"payment.amount":{"type":"integer"},"device.is_emulator":{"type":"boolean"},"risk.score":{"type":"float"}}}"#;

    #[test]
    fn compiles_simple_rule() {
        let reg = SignalRegistry::from_json_bytes(REG_JSON.as_bytes()).unwrap();
        let yaml = r#"
version: 1
rules:
  - id: high_amount
    expression:
      kind: compare_signal
      signal_name: payment.amount
      op: gte
      expected: 5000
"#;
        let rs = compile_yaml_rule_set(yaml, &reg).unwrap();
        assert_eq!(rs.version, 1);
        assert_eq!(rs.rules.len(), 1);
        assert_eq!(rs.rules[0].id, "high_amount");
    }

    #[test]
    fn undefined_signal_includes_line_and_suggestion() {
        let reg = SignalRegistry::from_json_bytes(REG_JSON.as_bytes()).unwrap();
        let yaml = r#"version: 1
rules:
  - id: bad
    expression:
      kind: compare_signal
      signal_name: payment.amunt
      op: eq
      expected: 1
"#;
        let err = compile_yaml_rule_set(yaml, &reg).unwrap_err();
        assert!(err.message.contains("payment.amunt"));
        assert_eq!(err.line, Some(6));
        assert_eq!(err.suggestion.as_deref(), Some("payment.amount"));
    }
}
