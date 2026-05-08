//! Standard Heavy Rule Set — content-addressed AND tree with 120+ compare leaves (full trace + manifest).
//!
//! Used by CI to regress **p99** wall time versus `origin/main` (see `.github/workflows/tarka-core-benchmark-regression.yml`).

use std::hint::black_box;
use std::time::Duration;

use criterion::{criterion_group, criterion_main, Criterion};
use serde_json::{json, Value};
use tarka_core::engine::{CompareOp, MockExternal};
use tarka_core::{
    parse_verified_rule_json, rule_content_sha256, Evaluator, RuleExpr, TraceContext,
};

/// Minimum leaf count for the “standard heavy” scenario (policy-as-code scale).
const STANDARD_HEAVY_LEAF_COUNT: usize = 120;

fn build_standard_heavy_rule_json() -> (Vec<u8>, String) {
    let children: Vec<RuleExpr> = (0..STANDARD_HEAVY_LEAF_COUNT)
        .map(|i| RuleExpr::CompareLeaf {
            id: format!("heavy.leaf.{i}"),
            path: format!("/f{i}"),
            op: CompareOp::Eq,
            expected: json!(1),
        })
        .collect();

    let root = RuleExpr::And {
        id: "standard_heavy_root".into(),
        children,
    };

    let bytes = serde_json::to_vec(&root).expect("serialize standard heavy rule");
    let hex = hex::encode(rule_content_sha256(&bytes));
    (bytes, hex)
}

fn matching_payload() -> Value {
    let mut obj = serde_json::Map::new();
    for i in 0..STANDARD_HEAVY_LEAF_COUNT {
        obj.insert(format!("f{i}"), json!(1));
    }
    Value::Object(obj)
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

fn bench_standard_heavy_evaluate(c: &mut Criterion) {
    let (rule_bytes, content_id_hex) = build_standard_heavy_rule_json();
    let root = parse_verified_rule_json(&rule_bytes, &content_id_hex).expect("verified parse");
    let data = matching_payload();

    let mut group = c.benchmark_group("standard_heavy_rule_set");

    group.bench_function("evaluate_full_trace", |b| {
        b.iter(|| {
            let mut eval = Evaluator::new(
                root.clone(),
                TraceContext::new(),
                MockExternal::default(),
                "tarka-core-bench",
            );
            let (decision, outcome) = eval.evaluate(black_box(&data));
            black_box((decision, outcome.is_ok()))
        });
    });

    group.finish();
}

criterion_group! {
    name = benches;
    config = criterion_config();
    targets = bench_standard_heavy_evaluate
}
criterion_main!(benches);
