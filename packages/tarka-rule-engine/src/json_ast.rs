//! JSON rule `when_ast` parsing and evaluation (parity with decision-api AST).

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
struct AstParseCtx {
    rule_id: String,
    next_preorder: usize,
}

impl AstParseCtx {
    fn new(rule_id: impl Into<String>) -> Self {
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
            1 + children.iter().map(ast_depth).max().unwrap_or(0)
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
    if ast_depth(n) > MAX_AST_DEPTH {
        return Err(ctx.err(
            "ast_depth_exceeded",
            format!("depth exceeds maximum {MAX_AST_DEPTH}"),
            path.to_string(),
            node_index,
        ));
    }
    if ast_count(n) > MAX_AST_NODES {
        return Err(ctx.err(
            "ast_node_count_exceeded",
            format!("node count exceeds maximum {MAX_AST_NODES}"),
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
            let value = obj.get("value").cloned().unwrap_or(Value::Null);
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
            let output_key = obj
                .get("output_key")
                .and_then(|x| x.as_str())
                .unwrap_or("")
                .to_string();
            if plugin_id.is_empty() || output_key.is_empty() {
                return Err(ctx.err(
                    "ast_invalid_custom_signal",
                    "custom_signal requires plugin_id and output_key",
                    path.to_string(),
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
            if children_raw.is_empty() || children_raw.len() > MAX_AST_CHILDREN {
                return Err(ctx.err(
                    "ast_invalid_children",
                    "children must be non-empty and within limit",
                    format!("{path}.children"),
                    Some(node_index),
                ));
            }
            let mut children = Vec::with_capacity(children_raw.len());
            for (i, ch) in children_raw.iter().enumerate() {
                children.push(parse_ast_strict_ctx(ch, &format!("{path}.children[{i}]"), ctx)?);
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

use serde_json::Map;

pub fn eval_ast(node: &AstNode, features: &Map<String, Value>) -> bool {
    match node {
        AstNode::CustomSignal { .. } => true,
        AstNode::Condition {
            op,
            field,
            value,
            regex_compiled,
        } => {
            let c = crate::ruleset::Condition {
                op: op.clone(),
                field: field.clone(),
                value: value.clone(),
                regex_compiled: regex_compiled.clone(),
            };
            crate::ruleset::match_condition(features, &c)
        }
        AstNode::And { children } => children.iter().all(|c| eval_ast(c, features)),
        AstNode::Or { children } => children.iter().any(|c| eval_ast(c, features)),
    }
}
