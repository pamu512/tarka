//! Render a [`super::evaluator::RuleExpr`] tree as a [Mermaid](https://mermaid.js.org/) **flowchart** string.
//!
//! Composite gates use distinct shapes (hexagon = AND, stadium = OR, parallelogram = NOT); leaves use rectangles.

use super::evaluator::{CompareOp, RuleExpr};
use serde_json::Value;
use std::fmt::Write;
use thiserror::Error;

/// Upper bounds avoid hostile payloads exhausting memory when analysts paste arbitrary JSON.
pub const MAX_MERMAID_NODES: usize = 2048;
pub const MAX_MERMAID_DEPTH: usize = 128;

/// Failure building the diagram (oversized tree).
#[derive(Debug, Error)]
pub enum MermaidFlowchartError {
    #[error("rule tree exceeds maximum depth ({max})")]
    TooDeep { max: usize },
    #[error("rule tree exceeds maximum node count ({max})")]
    TooManyNodes { max: usize },
}

struct GenCtx<'a> {
    lines: &'a mut Vec<String>,
    seq: usize,
    nodes_emitted: usize,
}

impl GenCtx<'_> {
    fn next_id(&mut self) -> Result<String, MermaidFlowchartError> {
        if self.nodes_emitted >= MAX_MERMAID_NODES {
            return Err(MermaidFlowchartError::TooManyNodes {
                max: MAX_MERMAID_NODES,
            });
        }
        let id = format!("n{}", self.seq);
        self.seq += 1;
        self.nodes_emitted += 1;
        Ok(id)
    }
}

fn escape_label(text: &str) -> String {
    let t = text.trim();
    if t.is_empty() {
        return "(empty)".to_string();
    }
    let t = t.replace('"', "'");
    let t = t.replace('\n', " ");
    let max = 240usize;
    if t.chars().count() > max {
        let trunc: String = t.chars().take(max).collect();
        format!("{trunc}…")
    } else {
        t
    }
}

fn fmt_compare_op(op: CompareOp) -> &'static str {
    match op {
        CompareOp::Eq => "=",
        CompareOp::Ne => "≠",
        CompareOp::Lt => "<",
        CompareOp::Lte => "≤",
        CompareOp::Gt => ">",
        CompareOp::Gte => "≥",
        CompareOp::StringContains => "contains",
    }
}

fn fmt_json_compact(v: &Value, max_len: usize) -> String {
    match serde_json::to_string(v) {
        Ok(s) if s.len() <= max_len => s,
        Ok(s) => format!("{}…", &s[..max_len.saturating_sub(1)]),
        Err(_) => "\"?\"".to_string(),
    }
}

fn leaf_label(expr: &RuleExpr) -> String {
    match expr {
        RuleExpr::CompareLeaf {
            path,
            op,
            expected,
            id,
        } => {
            format!(
                "{} {} {} · {}",
                path,
                fmt_compare_op(*op),
                fmt_json_compact(expected, 96),
                escape_label(id)
            )
        }
        RuleExpr::RedisCompareLeaf {
            redis_key,
            op,
            expected,
            id,
        } => {
            format!(
                "redis[{redis_key}] {} {} · {}",
                fmt_compare_op(*op),
                fmt_json_compact(expected, 80),
                escape_label(id)
            )
        }
        RuleExpr::ListContainsLeaf {
            list_name,
            item_path,
            id,
        } => format!(
            "list_contains({list_name}, {item_path}) · {}",
            escape_label(id)
        ),
        RuleExpr::CustomLeaf { name, id } => {
            format!("custom({}) · {}", escape_label(name), escape_label(id))
        }
        RuleExpr::WasmCustomLeaf {
            wasm_content_id_hex,
            name,
            export,
            id,
        } => {
            let nm = name
                .as_deref()
                .filter(|s| !s.is_empty())
                .unwrap_or(wasm_content_id_hex.as_str());
            format!(
                "wasm {} export({}) · {}",
                escape_label(nm),
                escape_label(export),
                escape_label(id)
            )
        }
        RuleExpr::And { .. }
        | RuleExpr::Or { .. }
        | RuleExpr::Not { .. } => "(unexpected composite)".to_string(),
    }
}

fn emit_hex_and(ctx: &mut GenCtx, logic_label: &str, rule_id: &str) -> Result<String, MermaidFlowchartError> {
    let id = ctx.next_id()?;
    let label = format!("AND · {}", escape_label(rule_id));
    let inner = escape_label(&format!("∧ {logic_label}<br/>{label}"));
    // Mermaid hexagon: id{{"label"}} → brace escaping in format!: {{{{ … }}}}.
    let line = format!("    {} {{{{\"{}\"}}}}", id, inner);
    ctx.lines.push(line);
    Ok(id)
}

fn emit_stadium_or(ctx: &mut GenCtx, logic_label: &str, rule_id: &str) -> Result<String, MermaidFlowchartError> {
    let id = ctx.next_id()?;
    let label = format!("OR · {}", escape_label(rule_id));
    let inner = escape_label(&format!("∨ {logic_label}<br/>{label}"));
    let line = format!("    {}([\"{}\"])", id, inner);
    ctx.lines.push(line);
    Ok(id)
}

fn emit_trap_not(ctx: &mut GenCtx, rule_id: &str) -> Result<String, MermaidFlowchartError> {
    let id = ctx.next_id()?;
    let line = format!(
        "    {id}[/{}/]",
        escape_label(&format!("NOT · {}", escape_label(rule_id)))
    );
    ctx.lines.push(line);
    Ok(id)
}

fn emit_leaf_rect(ctx: &mut GenCtx, expr: &RuleExpr) -> Result<String, MermaidFlowchartError> {
    let id = ctx.next_id()?;
    let lab = leaf_label(expr);
    ctx
        .lines
        .push(format!("    {}[\"{}\"]", id, escape_label(&lab)));
    Ok(id)
}

fn link(parent: &str, child: &str, lines: &mut Vec<String>) {
    lines.push(format!("    {parent} --> {child}"));
}

fn walk(
    expr: &RuleExpr,
    parent_id: Option<&str>,
    depth: usize,
    ctx: &mut GenCtx,
) -> Result<String, MermaidFlowchartError> {
    if depth > MAX_MERMAID_DEPTH {
        return Err(MermaidFlowchartError::TooDeep {
            max: MAX_MERMAID_DEPTH,
        });
    }

    let node_id = match expr {
        RuleExpr::And { id, children } => {
            let nid = emit_hex_and(ctx, "all must hold", id)?;
            if let Some(p) = parent_id {
                link(p, &nid, ctx.lines);
            }
            for ch in children {
                walk(ch, Some(&nid), depth + 1, ctx)?;
            }
            nid
        }
        RuleExpr::Or { id, children } => {
            let nid = emit_stadium_or(ctx, "any may hold", id)?;
            if let Some(p) = parent_id {
                link(p, &nid, ctx.lines);
            }
            for ch in children {
                let _ = walk(ch, Some(&nid), depth + 1, ctx)?;
            }
            nid
        }
        RuleExpr::Not { id, child } => {
            let nid = emit_trap_not(ctx, id)?;
            if let Some(p) = parent_id {
                link(p, &nid, ctx.lines);
            }
            let _ = walk(child, Some(&nid), depth + 1, ctx)?;
            nid
        }
        leaf @ (RuleExpr::CompareLeaf { .. }
        | RuleExpr::RedisCompareLeaf { .. }
        | RuleExpr::ListContainsLeaf { .. }
        | RuleExpr::CustomLeaf { .. }
        | RuleExpr::WasmCustomLeaf { .. }) => {
            let nid = emit_leaf_rect(ctx, leaf)?;
            if let Some(p) = parent_id {
                link(p, &nid, ctx.lines);
            }
            nid
        }
    };

    Ok(node_id)
}

/// Build a Mermaid **flowchart TD** document for the given rule tree (engine [`RuleExpr`]).
///
/// - **AND** → hexagon `{{…}}`
/// - **OR** → stadium `([…])`
/// - **NOT** → parallelogram `[/…/]`
/// - **Leaves** → rectangle `["…"]`
pub fn rule_expr_to_mermaid_flowchart(expr: &RuleExpr) -> Result<String, MermaidFlowchartError> {
    let mut lines: Vec<String> = Vec::new();
    lines.push("flowchart TD".to_string());
    lines.push("    %% Tarka RuleExpr — generated by tarka-core".to_string());

    let mut ctx = GenCtx {
        lines: &mut lines,
        seq: 0,
        nodes_emitted: 0,
    };

    let _root = walk(expr, None, 0, &mut ctx)?;

    let mut out = String::new();
    for line in lines {
        writeln!(out, "{line}").expect("string write");
    }
    Ok(out.trim_end().to_string() + "\n")
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn renders_and_or_not_leaves() {
        let tree = RuleExpr::And {
            id: "root".into(),
            children: vec![
                RuleExpr::Or {
                    id: "inner_or".into(),
                    children: vec![
                        RuleExpr::CompareLeaf {
                            id: "l1".into(),
                            path: "/a".into(),
                            op: CompareOp::Eq,
                            expected: json!(1),
                        },
                        RuleExpr::Not {
                            id: "n1".into(),
                            child: Box::new(RuleExpr::CompareLeaf {
                                id: "l2".into(),
                                path: "/b".into(),
                                op: CompareOp::StringContains,
                                expected: json!("x"),
                            }),
                        },
                    ],
                },
                RuleExpr::CompareLeaf {
                    id: "l3".into(),
                    path: "/c".into(),
                    op: CompareOp::Gte,
                    expected: json!(0),
                },
            ],
        };
        let s = rule_expr_to_mermaid_flowchart(&tree).expect("mermaid");
        assert!(s.starts_with("flowchart TD"));
        assert!(s.contains("{{\""));
        assert!(s.contains("([\""));
        assert!(s.contains("[/"));
        assert!(s.contains("-->"));
        assert!(s.contains("/a"));
        assert!(s.contains("/c"));
    }

    #[test]
    fn too_deep_errors() {
        fn deep_or_chain(depth: usize) -> RuleExpr {
            if depth == 0 {
                RuleExpr::CompareLeaf {
                    id: "leaf".into(),
                    path: "/p".into(),
                    op: CompareOp::Eq,
                    expected: Value::Null,
                }
            } else {
                RuleExpr::Or {
                    id: format!("o{depth}"),
                    children: vec![deep_or_chain(depth - 1)],
                }
            }
        }
        let expr = deep_or_chain(MAX_MERMAID_DEPTH + 5);
        assert!(matches!(
            rule_expr_to_mermaid_flowchart(&expr),
            Err(MermaidFlowchartError::TooDeep { .. })
        ));
    }
}
