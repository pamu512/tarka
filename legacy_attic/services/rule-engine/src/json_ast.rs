//! JSON rule `when_ast` parsing and evaluation (parity with `decision_api.ast_models` / `ast_evaluator`).

use regex::Regex;
use serde_json::Value;
use std::collections::HashSet;
use std::sync::Arc;

pub const MAX_AST_DEPTH: usize = 24;
pub const MAX_AST_NODES: usize = 384;
pub const MAX_AST_CHILDREN: usize = 32;
pub const MAX_REGEX_PATTERN_LEN: usize = 256;

#[derive(Debug, Clone)]
pub struct AstMalformed {
    pub code: String,
    pub message: String,
    pub path: String,
    pub rule_id: Option<String>,
    pub ast_node_index: Option<usize>,
}

impl AstMalformed {
    pub fn new(
        code: impl Into<String>,
        message: impl Into<String>,
        path: impl Into<String>,
        rule_id: Option<String>,
        ast_node_index: Option<usize>,
    ) -> Self {
        Self {
            code: code.into(),
            message: message.into(),
            path: path.into(),
            rule_id,
            ast_node_index,
        }
    }
}

#[derive(Debug, Clone)]
pub enum AstNode {
    Condition {
        op: String,
        field: String,
        value: Value,
        regex_compiled: Option<Arc<Regex>>,
    },
    /// Resolved in Python before evaluation; Rust treats as a no-op (always true).
    CustomSignal {
        plugin_id: String,
        output_key: String,
    },
    And {
        children: Vec<AstNode>,
    },
    Or {
        children: Vec<AstNode>,
    },
}

#[derive(Debug, Clone)]
pub struct AstParseCtx {
    pub rule_id: String,
    next_preorder: usize,
}

impl AstParseCtx {
    pub fn new(rule_id: impl Into<String>) -> Self {
        Self {
            rule_id: rule_id.into(),
            next_preorder: 0,
        }
    }

    fn take_index(&mut self) -> usize {
        let i = self.next_preorder;
        self.next_preorder += 1;
        i
    }

    fn err(
        &self,
        code: impl Into<String>,
        message: impl Into<String>,
        path: impl Into<String>,
        ast_node_index: Option<usize>,
    ) -> AstMalformed {
        AstMalformed::new(
            code,
            message,
            path,
            Some(self.rule_id.clone()),
            ast_node_index,
        )
    }
}

fn ast_depth(n: &AstNode) -> usize {
    match n {
        AstNode::Condition { .. } | AstNode::CustomSignal { .. } => 1,
        AstNode::And { children } | AstNode::Or { children } => {
            let max_child = children.iter().map(ast_depth).max();
            1 + max_child.map_or(0, |d| d)
        }
    }
}

fn ast_count(n: &AstNode) -> usize {
    match n {
        AstNode::Condition { .. } | AstNode::CustomSignal { .. } => 1,
        AstNode::And { children } | AstNode::Or { children } => {
            1 + children.iter().map(ast_count).sum::<usize>()
        }
    }
}

fn enforce_limits(
    n: &AstNode,
    path: &str,
    ctx: &AstParseCtx,
    node_index: Option<usize>,
) -> Result<(), AstMalformed> {
    let d = ast_depth(n);
    if d > MAX_AST_DEPTH {
        return Err(ctx.err(
            "ast_depth_exceeded",
            format!("depth {d} exceeds maximum {MAX_AST_DEPTH}"),
            path.to_string(),
            node_index,
        ));
    }
    let c = ast_count(n);
    if c > MAX_AST_NODES {
        return Err(ctx.err(
            "ast_node_count_exceeded",
            format!("node count {c} exceeds maximum {MAX_AST_NODES}"),
            path.to_string(),
            node_index,
        ));
    }
    Ok(())
}

fn condition_allowed_keys() -> HashSet<&'static str> {
    HashSet::from(["type", "op", "field", "value"])
}

fn composite_allowed_keys() -> HashSet<&'static str> {
    HashSet::from(["type", "children"])
}

fn custom_signal_allowed_keys() -> HashSet<&'static str> {
    HashSet::from(["type", "plugin_id", "params", "output_key"])
}

fn build_safe_regex_pattern(pattern: &str) -> String {
    let escaped = regex::escape(pattern);
    format!("(?i)^{}$", escaped.replace(r"\*", ".*").replace(r"\?", "."))
}

/// Strict parse (GitOps / `validate_json_rule_ast`). Matches Pydantic `extra = forbid` on nodes.
pub fn parse_ast_strict(v: &Value, path: &str) -> Result<AstNode, AstMalformed> {
    let mut ctx = AstParseCtx::new("");
    parse_ast_strict_ctx(v, path, &mut ctx)
}

/// Strict parse with `rule_id` and AST node indices for diagnostics.
pub fn parse_ast_strict_in_rule(v: &Value, path: &str, rule_id: &str) -> Result<AstNode, AstMalformed> {
    let mut ctx = AstParseCtx::new(rule_id);
    parse_ast_strict_ctx(v, path, &mut ctx)
}

fn parse_ast_strict_ctx(
    v: &Value,
    path: &str,
    ctx: &mut AstParseCtx,
) -> Result<AstNode, AstMalformed> {
    let node_index = ctx.take_index();
    let obj = v.as_object().ok_or_else(|| {
        ctx.err(
            "ast_not_object",
            "AST node must be a JSON object",
            path.to_string(),
            Some(node_index),
        )
    })?;
    let typ = obj
        .get("type")
        .and_then(|x| x.as_str())
        .ok_or_else(|| {
            ctx.err(
                "ast_missing_type",
                "missing string field 'type'",
                path.to_string(),
                Some(node_index),
            )
        })?;
    match typ {
        "condition" => {
            for k in obj.keys() {
                if !condition_allowed_keys().contains(k.as_str()) {
                    return Err(ctx.err(
                        "ast_extra_key",
                        format!("unexpected key on condition node: {k}"),
                        format!("{path}.{k}"),
                        Some(node_index),
                    ));
                }
            }
            let op = obj
                .get("op")
                .and_then(|x| x.as_str())
                .unwrap_or("eq")
                .to_string();
            let allowed_ops = [
                "eq", "not_eq", "gte", "gt", "lte", "lt", "in", "not_in", "contains", "starts_with",
                "ends_with", "regex", "is_true", "is_false", "exists", "not_exists",
            ];
            if !allowed_ops.contains(&op.as_str()) {
                return Err(ctx.err(
                    "ast_unknown_op",
                    format!("unknown condition op: {op}"),
                    format!("{path}.op"),
                    Some(node_index),
                ));
            }
            let field = obj
                .get("field")
                .and_then(|x| x.as_str())
                .unwrap_or("")
                .to_string();
            if field.is_empty() {
                return Err(ctx.err(
                    "ast_invalid_field",
                    "condition.field must be non-empty",
                    format!("{path}.field"),
                    Some(node_index),
                ));
            }
            if field.len() > 128 {
                return Err(ctx.err(
                    "ast_field_too_long",
                    "condition.field exceeds maximum length",
                    format!("{path}.field"),
                    Some(node_index),
                ));
            }
            let value = obj.get("value").cloned().unwrap_or(Value::Null);
            if !value.is_null() && format!("{value}").len() > 1024 {
                return Err(ctx.err(
                    "ast_value_too_long",
                    "condition.value exceeds maximum serialized length",
                    format!("{path}.value"),
                    Some(node_index),
                ));
            }

            let regex_compiled = if op == "regex" {
                let pattern = value.as_str().unwrap_or("");
                if pattern.is_empty() || pattern.len() > MAX_REGEX_PATTERN_LEN {
                    return Err(ctx.err(
                        "ast_regex_pattern_invalid",
                        "regex pattern empty or too long",
                        format!("{path}.value"),
                        Some(node_index),
                    ));
                }
                let safe = build_safe_regex_pattern(pattern);
                let re = Regex::new(&safe).map_err(|e| {
                    ctx.err(
                        "ast_regex_compile_failed",
                        e.to_string(),
                        format!("{path}.value"),
                        Some(node_index),
                    )
                })?;
                Some(Arc::new(re))
            } else {
                None
            };

            let node = AstNode::Condition {
                op,
                field,
                value,
                regex_compiled,
            };
            enforce_limits(&node, path, ctx, Some(node_index))?;
            Ok(node)
        }
        "custom_signal" => {
            for k in obj.keys() {
                if !custom_signal_allowed_keys().contains(k.as_str()) {
                    return Err(ctx.err(
                        "ast_extra_key",
                        format!("unexpected key on custom_signal node: {k}"),
                        format!("{path}.{k}"),
                        Some(node_index),
                    ));
                }
            }
            let plugin_id = obj
                .get("plugin_id")
                .and_then(|x| x.as_str())
                .unwrap_or("")
                .to_string();
            if plugin_id.is_empty() || plugin_id.len() > 128 {
                return Err(ctx.err(
                    "ast_invalid_plugin_id",
                    "custom_signal.plugin_id must be 1..=128 chars",
                    format!("{path}.plugin_id"),
                    Some(node_index),
                ));
            }
            let output_key = obj
                .get("output_key")
                .and_then(|x| x.as_str())
                .unwrap_or("")
                .to_string();
            if output_key.is_empty() || output_key.len() > 128 {
                return Err(ctx.err(
                    "ast_invalid_output_key",
                    "custom_signal.output_key must be 1..=128 chars",
                    format!("{path}.output_key"),
                    Some(node_index),
                ));
            }
            let params = obj.get("params").cloned().unwrap_or(Value::Null);
            if !params.is_null() && !params.is_object() {
                return Err(ctx.err(
                    "ast_invalid_params",
                    "custom_signal.params must be a JSON object when present",
                    format!("{path}.params"),
                    Some(node_index),
                ));
            }
            let node = AstNode::CustomSignal {
                plugin_id,
                output_key,
            };
            enforce_limits(&node, path, ctx, Some(node_index))?;
            Ok(node)
        }
        "and" | "or" => {
            for k in obj.keys() {
                if !composite_allowed_keys().contains(k.as_str()) {
                    return Err(ctx.err(
                        "ast_extra_key",
                        format!("unexpected key on {typ} node: {k}"),
                        format!("{path}.{k}"),
                        Some(node_index),
                    ));
                }
            }
            let children_raw = obj.get("children").and_then(|x| x.as_array()).ok_or_else(|| {
                ctx.err(
                    "ast_missing_children",
                    format!("'{typ}' node requires array 'children'"),
                    format!("{path}.children"),
                    Some(node_index),
                )
            })?;
            if children_raw.is_empty() {
                return Err(ctx.err(
                    "ast_empty_children",
                    format!("'{typ}' node must have at least one child"),
                    format!("{path}.children"),
                    Some(node_index),
                ));
            }
            if children_raw.len() > MAX_AST_CHILDREN {
                return Err(ctx.err(
                    "ast_too_many_children",
                    format!("more than {MAX_AST_CHILDREN} children"),
                    format!("{path}.children"),
                    Some(node_index),
                ));
            }
            let mut children = Vec::with_capacity(children_raw.len());
            for (i, ch) in children_raw.iter().enumerate() {
                let p = format!("{path}.children[{i}]");
                children.push(parse_ast_strict_ctx(ch, &p, ctx)?);
            }
            let node = if typ == "and" {
                AstNode::And { children }
            } else {
                AstNode::Or { children }
            };
            enforce_limits(&node, path, ctx, Some(node_index))?;
            Ok(node)
        }
        other => Err(ctx.err(
            "ast_unknown_node_type",
            format!("unknown node type: {other}"),
            format!("{path}.type"),
            Some(node_index),
        )),
    }
}

/// Pack-rule soft parse: on any strict failure, return `None` (rule skipped) — parity with Python `pack_evaluator`.
#[allow(dead_code)]
pub fn parse_ast_soft_for_rule(v: &Value, path: &str) -> Option<AstNode> {
    parse_ast_strict_in_rule(v, path, "when_ast").ok()
}

use serde_json::Map;

/// Evaluate AST; condition matching is total for well-formed trees built by the strict parser.
pub fn eval_ast(node: &AstNode, features: &Map<String, Value>) -> bool {
    eval_ast_inner(node, features)
}

fn eval_ast_inner(node: &AstNode, features: &Map<String, Value>) -> bool {
    match node {
        AstNode::CustomSignal {
            plugin_id,
            output_key,
        } => {
            let _ = (plugin_id, output_key);
            true
        }
        AstNode::Condition {
            op,
            field,
            value,
            regex_compiled,
        } => {
            let c = crate::Condition {
                op: op.clone(),
                field: field.clone(),
                value: value.clone(),
                regex_compiled: regex_compiled.clone(),
            };
            crate::match_condition(features, &c)
        }
        AstNode::And { children } => children
            .iter()
            .all(|child| eval_ast_inner(child, features)),
        AstNode::Or { children } => children
            .iter()
            .any(|child| eval_ast_inner(child, features)),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn strict_rejects_empty_condition_field() {
        let v = json!({"type": "condition", "op": "eq", "field": "", "value": 1});
        assert!(parse_ast_strict(&v, "$").is_err());
    }

    #[test]
    fn soft_parse_returns_none_on_invalid() {
        let v = json!({"type": "condition", "op": "eq", "field": "", "value": 1});
        assert!(parse_ast_soft_for_rule(&v, "when_ast").is_none());
    }

    #[test]
    fn eval_simple_and() {
        let v = json!({
            "type": "and",
            "children": [
                {"type": "condition", "op": "gte", "field": "amount", "value": 5000},
                {"type": "condition", "op": "is_true", "field": "is_vpn"},
            ]
        });
        let parsed = parse_ast_strict(&v, "$");
        assert!(parsed.is_ok(), "{:?}", parsed.as_ref().err());
        if let Ok(ast) = parsed {
            let mut m = Map::new();
            m.insert("amount".to_string(), json!(6000));
            m.insert("is_vpn".to_string(), json!(true));
            assert!(eval_ast(&ast, &m));
        }
    }

    #[test]
    fn custom_signal_parses_and_is_noop_for_eval() {
        let v = json!({
            "type": "and",
            "children": [
                {"type": "custom_signal", "plugin_id": "demo", "params": {"k": 1}, "output_key": "x"},
                {"type": "condition", "op": "gte", "field": "x", "value": 0.5},
            ]
        });
        let parsed = parse_ast_strict(&v, "$");
        assert!(parsed.is_ok(), "{:?}", parsed.as_ref().err());
        if let Ok(ast) = parsed {
            let mut m = Map::new();
            m.insert("x".to_string(), json!(0.9));
            assert!(eval_ast(&ast, &m));
        }
    }
}
