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
    GraphV1 {
        atom: String,
        etype: Option<String>,
        role: Option<String>,
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
        AstNode::Condition { .. } | AstNode::CustomSignal { .. } | AstNode::GraphV1 { .. } => 1,
        AstNode::And { children } | AstNode::Or { children } => {
            1 + children.iter().map(ast_depth).max().unwrap_or(0)
        }
    }
}

fn ast_count(n: &AstNode) -> usize {
    match n {
        AstNode::Condition { .. } | AstNode::CustomSignal { .. } | AstNode::GraphV1 { .. } => 1,
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

fn graph_v1_allowed_keys() -> HashSet<&'static str> {
    HashSet::from(["type", "atom", "etype", "role"])
}

fn norm_etype(raw: &str) -> String {
    raw.trim().to_ascii_uppercase().replace([' ', '-'], "_")
}

fn etype_token_ok(token: &str) -> bool {
    let mut chars = token.chars();
    match chars.next() {
        Some(c) if c.is_ascii_alphabetic() => {
            token.len() <= 64 && chars.all(|c| c.is_ascii_alphanumeric() || c == '_')
        }
        _ => false,
    }
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
        "graph_v1" => {
            for k in obj.keys() {
                if !graph_v1_allowed_keys().contains(k.as_str()) {
                    return Err(ctx.err(
                        "ast_extra_key",
                        format!("unexpected key on graph_v1 node: {k}"),
                        format!("{path}.{k}"),
                        Some(node_index),
                    ));
                }
            }
            let atom = obj
                .get("atom")
                .and_then(|x| x.as_str())
                .unwrap_or("")
                .to_string();
            if !matches!(
                atom.as_str(),
                "has_etype" | "has_multi_id" | "sibling_prior_flag"
            ) {
                return Err(ctx.err(
                    "ast_invalid_graph_v1",
                    format!("unknown graph_v1 atom: {atom}"),
                    format!("{path}.atom"),
                    Some(node_index),
                ));
            }
            let etype = obj
                .get("etype")
                .and_then(|x| x.as_str())
                .map(|s| s.to_string());
            if atom == "has_etype" {
                let raw = etype.as_deref().unwrap_or("");
                let token = norm_etype(raw);
                if raw.is_empty() || !etype_token_ok(&token) || token == "RELATED" {
                    return Err(ctx.err(
                        "ast_unsigned_etype",
                        format!("unsigned etype: {raw}"),
                        format!("{path}.etype"),
                        Some(node_index),
                    ));
                }
            } else if etype.as_ref().is_some_and(|s| !s.is_empty()) {
                return Err(ctx.err(
                    "ast_invalid_graph_v1",
                    "etype is only valid on graph_v1.has_etype",
                    format!("{path}.etype"),
                    Some(node_index),
                ));
            }
            let role = obj
                .get("role")
                .and_then(|x| x.as_str())
                .map(|s| s.to_string());
            let node = AstNode::GraphV1 { atom, etype, role };
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

fn hop_status_missing(status: &str) -> bool {
    matches!(
        status,
        "graph:missing" | "graph:unavailable" | "graph:empty" | ""
    )
}

fn positive_flag(v: &Value) -> bool {
    match v {
        Value::Bool(true) => true,
        Value::Number(n) => n.as_i64() == Some(1) || n.as_u64() == Some(1),
        Value::String(s) => matches!(
            s.trim().to_ascii_lowercase().as_str(),
            "1" | "true" | "flag" | "flagged" | "fraud" | "block" | "blocked"
        ),
        _ => false,
    }
}

fn eval_graph_v1(
    features: &Map<String, Value>,
    atom: &str,
    etype: &Option<String>,
    role: &Option<String>,
) -> bool {
    let hop = match features.get("_graph_hop_v1").and_then(|v| v.as_object()) {
        Some(h) => h,
        None => return false,
    };
    let status = hop.get("status").and_then(|v| v.as_str()).unwrap_or("");
    if hop_status_missing(status) {
        return false;
    }
    if let Some(want_role) = role.as_deref().map(str::trim).filter(|s| !s.is_empty()) {
        let got = hop
            .get("roles")
            .and_then(|v| v.as_array())
            .is_some_and(|roles| {
                roles.iter().any(|r| {
                    r.as_str()
                        .is_some_and(|s| s.trim().eq_ignore_ascii_case(want_role))
                })
            });
        if !got {
            return false;
        }
    }
    match atom {
        "has_etype" => {
            let want = norm_etype(etype.as_deref().unwrap_or(""));
            if want.is_empty() || want == "RELATED" || !etype_token_ok(&want) {
                return false;
            }
            let Some(allowed) = hop.get("signed_etypes").and_then(|v| v.as_array()) else {
                return false;
            };
            if !allowed
                .iter()
                .any(|x| x.as_str().is_some_and(|s| s == want))
            {
                return false;
            }
            hop.get("named_edges")
                .and_then(|v| v.as_array())
                .is_some_and(|edges| {
                    edges.iter().any(|e| {
                        e.get("type")
                            .or_else(|| e.get("etype"))
                            .and_then(|t| t.as_str())
                            .is_some_and(|t| norm_etype(t) == want)
                    })
                })
        }
        "has_multi_id" => hop
            .get("multi_id_user_ids")
            .and_then(|v| v.as_array())
            .is_some_and(|ids| ids.iter().any(|x| x.as_str().is_some_and(|s| !s.is_empty()))),
        "sibling_prior_flag" => hop
            .get("sibling_flags")
            .and_then(|v| v.as_object())
            .is_some_and(|flags| flags.values().any(positive_flag)),
        _ => false,
    }
}

pub fn eval_ast(node: &AstNode, features: &Map<String, Value>) -> bool {
    match node {
        AstNode::GraphV1 { atom, etype, role } => eval_graph_v1(features, atom, etype, role),
        AstNode::CustomSignal { output_key, .. } => !output_key.is_empty()
            && features.contains_key(output_key),
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

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::{json, Map, Value};

    fn hop_features() -> Map<String, Value> {
        json!({
            "_graph_hop_v1": {
                "status": "graph:ok",
                "named_edges": [
                    {"from_id": "alice", "to_id": "dev-1", "type": "USES_DEVICE"}
                ],
                "multi_id_user_ids": ["bob"],
                "sibling_flags": {"bob": "1"},
                "signed_etypes": ["USES_DEVICE", "USED", "SEEN_AT", "PARTY_WITH"]
            }
        })
        .as_object()
        .cloned()
        .unwrap()
    }

    #[test]
    fn graph_v1_shared_device_and_flagged_sibling() {
        let ast = parse_ast_strict_in_rule(
            &json!({
                "type": "and",
                "children": [
                    {"type": "graph_v1", "atom": "has_etype", "etype": "USES_DEVICE"},
                    {"type": "graph_v1", "atom": "has_multi_id"},
                    {"type": "graph_v1", "atom": "sibling_prior_flag"}
                ]
            }),
            "when_ast",
            "r1",
        )
        .unwrap();
        assert!(eval_ast(&ast, &hop_features()));
    }

    #[test]
    fn graph_v1_missing_hop_does_not_fire() {
        let ast = parse_ast_strict_in_rule(
            &json!({"type": "graph_v1", "atom": "has_etype", "etype": "USES_DEVICE"}),
            "when_ast",
            "r1",
        )
        .unwrap();
        let missing = json!({
            "_graph_hop_v1": {"status": "graph:missing", "named_edges": [], "multi_id_user_ids": []}
        })
        .as_object()
        .cloned()
        .unwrap();
        assert!(!eval_ast(&ast, &missing));
    }

    #[test]
    fn graph_v1_unsigned_etype_misses_without_signed_set() {
        let ast = parse_ast_strict_in_rule(
            &json!({"type": "graph_v1", "atom": "has_etype", "etype": "USES_DEVICE"}),
            "when_ast",
            "r1",
        )
        .unwrap();
        let hop = json!({
            "_graph_hop_v1": {
                "status": "graph:ok",
                "named_edges": [
                    {"from_id": "alice", "to_id": "dev-1", "type": "USES_DEVICE"}
                ]
            }
        })
        .as_object()
        .cloned()
        .unwrap();
        assert!(!eval_ast(&ast, &hop));
    }

    #[test]
    fn graph_v1_refuses_related_etype() {
        let err = parse_ast_strict_in_rule(
            &json!({"type": "graph_v1", "atom": "has_etype", "etype": "RELATED"}),
            "when_ast",
            "r1",
        )
        .unwrap_err();
        assert_eq!(err.code, "ast_unsigned_etype");
    }

    fn shipped_uses_device_ast() -> AstNode {
        let pack: Value = serde_json::from_str(include_str!(
            "../../../services/decision-api/rules/graph_v1_uses_device_v1.json"
        ))
        .unwrap();
        parse_ast_strict_in_rule(&pack["rules"][0]["when_ast"], "when_ast", "uses_device")
            .unwrap()
    }

    #[test]
    fn shipped_pack_flags_uses_device_plus_multi_id() {
        assert!(eval_ast(&shipped_uses_device_ast(), &hop_features()));
    }

    #[test]
    fn shipped_pack_misses_on_graph_missing() {
        let missing = json!({
            "_graph_hop_v1": {"status": "graph:missing", "named_edges": [], "multi_id_user_ids": []}
        })
        .as_object()
        .cloned()
        .unwrap();
        assert!(!eval_ast(&shipped_uses_device_ast(), &missing));
    }

    #[test]
    fn shipped_pack_misses_related_etype() {
        let hop = json!({
            "_graph_hop_v1": {
                "status": "graph:ok",
                "named_edges": [
                    {"from_id": "alice", "to_id": "dev-1", "type": "RELATED"}
                ],
                "multi_id_user_ids": ["bob"],
                "sibling_flags": {"bob": "1"},
                "signed_etypes": ["USES_DEVICE"]
            }
        })
        .as_object()
        .cloned()
        .unwrap();
        assert!(!eval_ast(&shipped_uses_device_ast(), &hop));
    }

    #[test]
    fn shipped_pack_replay_reads_stored_hop_fields() {
        let ast = shipped_uses_device_ast();
        let live = hop_features();
        let stored = live.get("_graph_hop_v1").cloned().unwrap();
        let replay = json!({ "_graph_hop_v1": stored })
            .as_object()
            .cloned()
            .unwrap();
        assert_eq!(eval_ast(&ast, &live), eval_ast(&ast, &replay));
        assert!(eval_ast(&ast, &live));
    }

    #[test]
    fn shipped_pack_flags_sibling_prior_without_multi_id() {
        let hop = json!({
            "_graph_hop_v1": {
                "status": "graph:ok",
                "named_edges": [
                    {"from_id": "alice", "to_id": "dev-1", "type": "USES_DEVICE"}
                ],
                "multi_id_user_ids": [],
                "sibling_flags": {"bob": "FLAG"},
                "signed_etypes": ["USES_DEVICE"]
            }
        })
        .as_object()
        .cloned()
        .unwrap();
        assert!(eval_ast(&shipped_uses_device_ast(), &hop));
    }

    fn shipped_instrument_ast() -> AstNode {
        let pack: Value = serde_json::from_str(include_str!(
            "../../../services/decision-api/rules/graph_v1_has_instrument_v1.json"
        ))
        .unwrap();
        parse_ast_strict_in_rule(&pack["rules"][0]["when_ast"], "when_ast", "has_instrument")
            .unwrap()
    }

    fn instrument_hop_features() -> Map<String, Value> {
        json!({
            "_graph_hop_v1": {
                "status": "graph:ok",
                "named_edges": [
                    {"from_id": "alice", "to_id": "email:sold@x.com", "type": "HAS_EMAIL"}
                ],
                "multi_id_user_ids": ["bob"],
                "sibling_flags": {"bob": "1"},
                "signed_etypes": ["HAS_EMAIL", "HAS_PHONE", "HAS_CARD"]
            }
        })
        .as_object()
        .cloned()
        .unwrap()
    }

    #[test]
    fn shipped_instrument_pack_flags_email_plus_multi_id() {
        assert!(eval_ast(&shipped_instrument_ast(), &instrument_hop_features()));
    }

    #[test]
    fn shipped_instrument_pack_misses_on_graph_missing() {
        let missing = json!({
            "_graph_hop_v1": {"status": "graph:missing", "named_edges": [], "multi_id_user_ids": []}
        })
        .as_object()
        .cloned()
        .unwrap();
        assert!(!eval_ast(&shipped_instrument_ast(), &missing));
    }

    #[test]
    fn shipped_instrument_pack_replay_reads_stored_hop_fields() {
        let ast = shipped_instrument_ast();
        let live = instrument_hop_features();
        let stored = live.get("_graph_hop_v1").cloned().unwrap();
        let replay = json!({ "_graph_hop_v1": stored })
            .as_object()
            .cloned()
            .unwrap();
        assert_eq!(eval_ast(&ast, &live), eval_ast(&ast, &replay));
        assert!(eval_ast(&ast, &live));
    }
}
