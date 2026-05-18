//! Recursive type checking: registry [`SignalType`](super::signal_type::SignalType) vs comparison operators and YAML `expected` values.

use super::error::CompileError;
use super::locate::line_for_signal_assignment;
use super::registry::SignalRegistry;
use super::signal_type::SignalType;
use super::yaml::YamlExpr;

/// Stateful façade for recursive validation (registry + optional YAML source lines).
pub struct TypeChecker<'a> {
    registry: &'a SignalRegistry,
}

impl<'a> TypeChecker<'a> {
    #[must_use]
    pub fn new(registry: &'a SignalRegistry) -> Self {
        Self { registry }
    }

    pub fn check_expr(&self, expr: &YamlExpr, yaml_source: &str) -> Result<(), CompileError> {
        type_check_expr(expr, self.registry, yaml_source)
    }
}

/// Walk the rule expression tree and ensure every `compare_signal` is valid for the signal's type.
pub fn type_check_expr(
    expr: &YamlExpr,
    registry: &SignalRegistry,
    yaml_source: &str,
) -> Result<(), CompileError> {
    match expr {
        YamlExpr::And { children } | YamlExpr::Or { children } => {
            for c in children {
                type_check_expr(c, registry, yaml_source)?;
            }
            Ok(())
        }
        YamlExpr::Not { child } => type_check_expr(child, registry, yaml_source),
        YamlExpr::CompareSignal {
            signal_name,
            op,
            expected,
        } => type_check_compare_leaf(signal_name, op, expected, registry, yaml_source),
    }
}

fn type_check_compare_leaf(
    signal_name: &str,
    op: &str,
    expected: &serde_yaml::Value,
    registry: &SignalRegistry,
    yaml_source: &str,
) -> Result<(), CompileError> {
    let name = signal_name.trim();
    let op_norm = op.trim().to_ascii_lowercase();
    let line = line_for_signal_assignment(yaml_source, name);

    let Some(sty) = registry.signal_type(name) else {
        return Err(CompileError::validation(
            format!("internal: missing registry type for signal `{name}`"),
            line,
        ));
    };

    if !ops_allowed_for_type(sty, &op_norm) {
        return Err(CompileError::validation(
            format!(
                "operator `{op_norm}` is not valid for signal `{name}` (type {}); allowed: {}",
                sty.label(),
                ops_list_for_type(sty)
            ),
            line,
        ));
    }

    check_expected_shape(sty, expected, name, &op_norm, line)?;

    Ok(())
}

fn ops_allowed_for_type(ty: SignalType, op: &str) -> bool {
    match ty {
        SignalType::Boolean => matches!(op, "eq" | "ne"),
        SignalType::Integer | SignalType::Float => {
            matches!(op, "eq" | "ne" | "lt" | "lte" | "gt" | "gte")
        }
        SignalType::String => matches!(
            op,
            "eq" | "ne" | "lt" | "lte" | "gt" | "gte" | "string_contains"
        ),
        SignalType::List => matches!(op, "eq" | "ne"),
    }
}

fn ops_list_for_type(ty: SignalType) -> &'static str {
    match ty {
        SignalType::Boolean => "eq, ne",
        SignalType::Integer | SignalType::Float => "eq, ne, lt, lte, gt, gte",
        SignalType::String => "eq, ne, lt, lte, gt, gte, string_contains",
        SignalType::List => "eq, ne",
    }
}

fn check_expected_shape(
    sty: SignalType,
    expected: &serde_yaml::Value,
    signal_name: &str,
    op: &str,
    line: Option<u32>,
) -> Result<(), CompileError> {
    match sty {
        SignalType::Boolean => {
            if !matches!(expected, serde_yaml::Value::Bool(_)) {
                return Err(CompileError::validation(
                    format!(
                        "signal `{signal_name}` is Boolean: `expected` must be a YAML boolean (true/false)"
                    ),
                    line,
                ));
            }
        }
        SignalType::Integer => {
            match expected {
                serde_yaml::Value::Number(n) => {
                    if !yaml_number_is_integral(n) {
                        return Err(CompileError::validation(
                            format!(
                                "signal `{signal_name}` is Integer: `expected` must be an integral number"
                            ),
                            line,
                        ));
                    }
                }
                _ => {
                    return Err(CompileError::validation(
                        format!(
                            "signal `{signal_name}` is Integer: `expected` must be a YAML integer number"
                        ),
                        line,
                    ));
                }
            }
        }
        SignalType::Float => {
            if !matches!(expected, serde_yaml::Value::Number(_)) {
                return Err(CompileError::validation(
                    format!(
                        "signal `{signal_name}` is Float: `expected` must be a YAML number"
                    ),
                    line,
                ));
            }
        }
        SignalType::String => {
            if op == "string_contains" {
                if !matches!(expected, serde_yaml::Value::String(_)) {
                    return Err(CompileError::validation(
                        format!(
                            "signal `{signal_name}`: `string_contains` requires a string `expected` value"
                        ),
                        line,
                    ));
                }
            } else if !matches!(expected, serde_yaml::Value::String(_)) {
                return Err(CompileError::validation(
                    format!(
                        "signal `{signal_name}` is String: `expected` must be a YAML string for operator `{op}`"
                    ),
                    line,
                ));
            }
        }
        SignalType::List => {
            match expected {
                serde_yaml::Value::Sequence(_) => {}
                serde_yaml::Value::String(s) => {
                    let t = s.trim();
                    let jv: serde_json::Value = serde_json::from_str(t).map_err(|e| {
                        CompileError::validation(
                            format!(
                                "signal `{signal_name}` is List: string `expected` must be valid JSON (array): {e}"
                            ),
                            line,
                        )
                    })?;
                    if !jv.is_array() {
                        return Err(CompileError::validation(
                            format!(
                                "signal `{signal_name}` is List: string `expected` must be a JSON array"
                            ),
                            line,
                        ));
                    }
                }
                _ => {
                    return Err(CompileError::validation(
                        format!(
                            "signal `{signal_name}` is List: `expected` must be a YAML sequence or JSON-array string"
                        ),
                        line,
                    ));
                }
            }
        }
    }
    Ok(())
}

fn yaml_number_is_integral(n: &serde_yaml::Number) -> bool {
    if n.as_i64().is_some() || n.as_u64().is_some() {
        return true;
    }
    n.as_f64()
        .map(|f| f.is_finite() && f.fract().abs() <= f64::EPSILON && f.abs() <= i64::MAX as f64)
        .unwrap_or(false)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::compiler::SignalRegistry;

    fn reg_typed() -> SignalRegistry {
        let j = r#"{
            "signals": {
                "b": { "type": "boolean" },
                "i": { "type": "integer" },
                "f": { "type": "float" },
                "s": { "type": "string" },
                "l": { "type": "list" }
            }
        }"#;
        SignalRegistry::from_json_bytes(j.as_bytes()).unwrap()
    }

    #[test]
    fn rejects_gt_on_boolean() {
        let reg = reg_typed();
        let ex = YamlExpr::CompareSignal {
            signal_name: "b".into(),
            op: "gt".into(),
            expected: serde_yaml::from_str("true").unwrap(),
        };
        let err = type_check_expr(&ex, &reg, "signal_name: b\n").unwrap_err();
        assert!(err.message.contains("gt"), "{}", err.message);
        assert!(err.message.contains("Boolean"), "{}", err.message);
    }

    #[test]
    fn accepts_boolean_eq() {
        let reg = reg_typed();
        let ex = YamlExpr::CompareSignal {
            signal_name: "b".into(),
            op: "eq".into(),
            expected: serde_yaml::from_str("false").unwrap(),
        };
        type_check_expr(&ex, &reg, "").unwrap();
    }

    #[test]
    fn rejects_string_contains_on_integer() {
        let reg = reg_typed();
        let ex = YamlExpr::CompareSignal {
            signal_name: "i".into(),
            op: "string_contains".into(),
            expected: serde_yaml::from_str("1").unwrap(),
        };
        let err = type_check_expr(&ex, &reg, "").unwrap_err();
        assert!(err.message.contains("string_contains"), "{}", err.message);
    }

    #[test]
    fn recursive_and_checks_all_leaves() {
        let reg = reg_typed();
        let ex = YamlExpr::And {
            children: vec![
                YamlExpr::CompareSignal {
                    signal_name: "b".into(),
                    op: "gte".into(),
                    expected: serde_yaml::from_str("true").unwrap(),
                },
                YamlExpr::CompareSignal {
                    signal_name: "i".into(),
                    op: "eq".into(),
                    expected: serde_yaml::from_str("1").unwrap(),
                },
            ],
        };
        let err = type_check_expr(&ex, &reg, "").unwrap_err();
        assert!(err.message.contains("gte"), "{}", err.message);
    }
}
