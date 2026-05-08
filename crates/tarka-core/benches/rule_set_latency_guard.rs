//! Baseline vs Proposed rule-set latency guard (Criterion).
//!
//! Two benchmarks share the group ``rule_set_latency_guard``:
//! - ``baseline_evaluate`` — Baseline rule tree (env ``TARKA_LG_BASELINE_*``).
//! - ``proposed_evaluate`` — Proposed rule tree (env ``TARKA_LG_PROPOSED_*``).
//!
//! CI compares expanded p99 nanoseconds; failure when Proposed exceeds Baseline by > threshold
//! (see ``scripts/ci/latency_violation_report.py``).

use std::hint::black_box;
use std::path::Path;
use std::time::Duration;

use criterion::{criterion_group, criterion_main, Criterion};
use serde_json::{json, Map, Value};
use tarka_core::engine::{CompareOp, MockExternal};
use tarka_core::{
    parse_verified_rule_json, rule_content_sha256, Evaluator, RuleExpr, TraceContext,
};

fn env_usize(key: &str, default_v: usize) -> usize {
    std::env::var(key)
        .ok()
        .and_then(|s| s.parse().ok())
        .unwrap_or(default_v)
}

fn build_and_compare_tree(leaf_count: usize, root_id_suffix: &str) -> (Vec<u8>, String) {
    let children: Vec<RuleExpr> = (0..leaf_count)
        .map(|i| RuleExpr::CompareLeaf {
            id: format!("lg.leaf.{i}"),
            path: format!("/f{i}"),
            op: CompareOp::Eq,
            expected: json!(1),
        })
        .collect();

    let root = RuleExpr::And {
        id: format!("latency_guard_{root_id_suffix}_{leaf_count}"),
        children,
    };

    let bytes = serde_json::to_vec(&root).expect("serialize rule tree");
    let hex = hex::encode(rule_content_sha256(&bytes));
    (bytes, hex)
}

fn matching_payload_flat_compare_leaves(leaf_count: usize) -> Value {
    let mut obj = Map::new();
    for i in 0..leaf_count {
        obj.insert(format!("f{i}"), json!(1));
    }
    Value::Object(obj)
}

fn collect_compare_leaf_bindings(expr: &RuleExpr, m: &mut Map<String, Value>) {
    match expr {
        RuleExpr::CompareLeaf {
            path, expected, ..
        } => {
            let key = path
                .trim_start_matches('/')
                .split('/')
                .filter(|s| !s.is_empty())
                .last()
                .unwrap_or(path.as_str())
                .to_string();
            m.insert(key, expected.clone());
        }
        RuleExpr::And { children, .. } | RuleExpr::Or { children, .. } => {
            for c in children {
                collect_compare_leaf_bindings(c, m);
            }
        }
        RuleExpr::Not { child, .. } => collect_compare_leaf_bindings(child, m),
        RuleExpr::RedisCompareLeaf { .. }
        | RuleExpr::ListContainsLeaf { .. }
        | RuleExpr::CustomLeaf { .. }
        | RuleExpr::WasmCustomLeaf { .. } => {}
    }
}

fn payload_for_rule(root: &RuleExpr) -> Value {
    let mut m = Map::new();
    collect_compare_leaf_bindings(root, &mut m);
    Value::Object(m)
}

fn load_rule_from_path(path: &Path) -> (RuleExpr, Value) {
    let bytes = std::fs::read(path).unwrap_or_else(|e| {
        panic!("Tarka latency guard: read {}: {e}", path.display());
    });
    let hex = hex::encode(rule_content_sha256(&bytes));
    let root = parse_verified_rule_json(&bytes, &hex)
        .unwrap_or_else(|e| panic!("Tarka latency guard: invalid rule {}: {e}", path.display()));
    let data = payload_for_rule(&root);
    (root, data)
}

fn baseline_rule_and_data() -> (RuleExpr, Value) {
    if let Ok(p) = std::env::var("TARKA_LG_BASELINE_RULE_PATH") {
        let path = Path::new(&p);
        return load_rule_from_path(path);
    }
    let n = env_usize("TARKA_LG_BASELINE_LEAVES", 120);
    let (bytes, hex) = build_and_compare_tree(n, "baseline");
    let root =
        parse_verified_rule_json(&bytes, &hex).expect("baseline generated rule must verify");
    let data = matching_payload_flat_compare_leaves(n);
    (root, data)
}

fn proposed_rule_and_data() -> (RuleExpr, Value) {
    if let Ok(p) = std::env::var("TARKA_LG_PROPOSED_RULE_PATH") {
        let path = Path::new(&p);
        return load_rule_from_path(path);
    }
    let n = env_usize("TARKA_LG_PROPOSED_LEAVES", 120);
    let (bytes, hex) = build_and_compare_tree(n, "proposed");
    let root =
        parse_verified_rule_json(&bytes, &hex).expect("proposed generated rule must verify");
    let data = matching_payload_flat_compare_leaves(n);
    (root, data)
}

fn criterion_config() -> Criterion {
    let mut c = Criterion::default();
    if std::env::var("CI").map(|v| v == "true").unwrap_or(false) {
        c = c
            .sample_size(80)
            .warm_up_time(Duration::from_secs(2))
            .measurement_time(Duration::from_secs(5));
    } else {
        c = c
            .sample_size(100)
            .warm_up_time(Duration::from_secs(3))
            .measurement_time(Duration::from_secs(8));
    }
    c
}

fn bench_rule_set_latency_guard(c: &mut Criterion) {
    let (base_root, base_data) = baseline_rule_and_data();
    let (prop_root, prop_data) = proposed_rule_and_data();

    let mut group = c.benchmark_group("rule_set_latency_guard");

    group.bench_function("baseline_evaluate", |b| {
        b.iter(|| {
            let mut eval = Evaluator::new(
                base_root.clone(),
                TraceContext::new(),
                MockExternal::default(),
                "tarka-core-latency-guard",
            );
            let (decision, outcome) = eval.evaluate(black_box(&base_data));
            black_box((decision, outcome.is_ok()))
        });
    });

    group.bench_function("proposed_evaluate", |b| {
        b.iter(|| {
            let mut eval = Evaluator::new(
                prop_root.clone(),
                TraceContext::new(),
                MockExternal::default(),
                "tarka-core-latency-guard",
            );
            let (decision, outcome) = eval.evaluate(black_box(&prop_data));
            black_box((decision, outcome.is_ok()))
        });
    });

    group.finish();
}

criterion_group! {
    name = benches;
    config = criterion_config();
    targets = bench_rule_set_latency_guard
}
criterion_main!(benches);
