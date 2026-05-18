//! Fuzz [`tarka_core::engine::Evaluator`] with adversarial JSON payloads.
//!
//! ## Running
//!
//! ```text
//! cargo install cargo-fuzz
//! cd fuzz && cargo fuzz run evaluator -- -runs=100000
//! ```
//!
//! ## Invariants (must hold for every input)
//!
//! - Evaluation never panics.
//! - For the same [`serde_json::Value`] payload, two successive evaluations produce:
//!   - the same boolean decision, and
//!   - the same ordered trace step identities (`rule_id`, `logic_operator`, `result`).
//!
//! Evidence manifests intentionally include timestamps / UUIDs and are **not** compared.
//!
//! ## Edge cases generated here (non-exhaustive)
//!
//! - **`Value::Null`** at root and nested positions (aligned with rules comparing `/a` to null).
//! - **Finite floats**: every bit pattern via `f64::from_bits(u64)` mapped through
//!   [`serde_json::Number::from_f64`] when valid; invalid float payloads fall back to stable integers.
//! - **±∞ / NaN**: explicit branches emit surrogate representations (`null`, strings, or bounded ints)
//!   because JSON numbers cannot represent non-finite values — while still stressing compare plumbing.
//! - **Deeply nested arrays/objects**: bounded recursion (`MAX_DEPTH`) with fan-out caps (`MAX_COLLECTION`).
//! - **Empty arrays/objects**, single-element nesting towers.
//! - **Wide integer spread**: `i64::MIN` / `i64::MAX`, `u64` bit patterns narrowed to `i64`, and zero.
//! - **Empty strings**, long binary-derived UTF-8-ish strings (via lossy conversion).
//! - **Sparse objects** with repeated keys (JSON semantics: last wins — deterministic).
//! - **Mixed-type comparisons**: strings vs numbers for ordering/containment paths in leaves.

#![no_main]

use arbitrary::Unstructured;
use libfuzzer_sys::fuzz_target;
use serde_json::{json, Number, Value};
use tarka_core::engine::{CompareOp, Evaluator, MockExternal, RuleExpr, TraceContext};

const MAX_DEPTH: u8 = 28;
const MAX_COLLECTION: usize = 24;

/// Fixed rule tree: `And` / `Or` / `Not` + [`CompareOp`] only (no Redis / list / custom / wasm),
/// so evaluation is a pure function of the JSON + engine version.
fn fixed_rule() -> RuleExpr {
    RuleExpr::And {
        id: "fuzz.root.and".into(),
        children: vec![
            RuleExpr::Or {
                id: "fuzz.root.or".into(),
                children: vec![
                    RuleExpr::CompareLeaf {
                        id: "fuzz.cmp.eq_null".into(),
                        path: "/a".into(),
                        op: CompareOp::Eq,
                        expected: Value::Null,
                    },
                    RuleExpr::Not {
                        id: "fuzz.not".into(),
                        child: Box::new(RuleExpr::CompareLeaf {
                            id: "fuzz.cmp.str_contains".into(),
                            path: "/label".into(),
                            op: CompareOp::StringContains,
                            expected: json!("needle"),
                        }),
                    },
                ],
            },
            RuleExpr::CompareLeaf {
                id: "fuzz.cmp.ordered".into(),
                path: "/score".into(),
                op: CompareOp::Gte,
                expected: json!(0),
            },
        ],
    }
}

fn arbitrary_number_from_unstructured(u: &mut Unstructured<'_>) -> arbitrary::Result<Value> {
    Ok(match u.int_in_range(0u8..=12)? {
        0 => Value::Number(Number::from(0)),
        1 => Value::Number(Number::from(u.int_in_range(i64::MIN..=i64::MAX)?)),
        2 => Value::Number(Number::from(u.int_in_range(u64::MIN..=u64::MAX)? as i64)),
        3 => {
            let bits: u64 = u.arbitrary()?;
            let f = f64::from_bits(bits);
            Value::Number(Number::from_f64(f).unwrap_or_else(|| Number::from(0)))
        }
        4 => Value::Null,
        5 => json!("nan_marker"),
        6 => json!("inf_marker"),
        7 => Value::Number(Number::from(i64::MIN)),
        8 => Value::Number(Number::from(i64::MAX)),
        9 => Value::Number(Number::from_f64(f64::MAX).unwrap_or_else(|| Number::from(0))),
        10 => Value::Number(Number::from_f64(f64::MIN_POSITIVE).unwrap_or_else(|| Number::from(0))),
        11 => Value::Number(Number::from_f64(-0.0).unwrap_or_else(|| Number::from(0))),
        _ => Value::Bool(u.arbitrary()?),
    })
}

fn take_raw_bytes(u: &mut Unstructured<'_>, len: usize) -> arbitrary::Result<Vec<u8>> {
    let mut buf = vec![0u8; len];
    if len > 0 {
        u.fill_buffer(&mut buf)?;
    }
    Ok(buf)
}

fn arbitrary_string_from_unstructured(u: &mut Unstructured<'_>) -> arbitrary::Result<Value> {
    let len = u.int_in_range(0usize..=384)?;
    let bytes = take_raw_bytes(u, len)?;
    let s = String::from_utf8_lossy(&bytes).into_owned();
    Ok(Value::String(s))
}

fn arbitrary_json_value(u: &mut Unstructured<'_>, depth: u8) -> arbitrary::Result<Value> {
    if depth >= MAX_DEPTH {
        return match u.int_in_range(0u8..=3)? {
            0 => Ok(Value::Null),
            1 => arbitrary_number_from_unstructured(u),
            2 => arbitrary_string_from_unstructured(u),
            _ => Ok(Value::Bool(u.arbitrary()?)),
        };
    }

    let tag = u.int_in_range(0u8..=12)?;
    match tag {
        0 | 6 => Ok(Value::Null),
        1 => Ok(Value::Bool(u.arbitrary()?)),
        2 => arbitrary_number_from_unstructured(u),
        3 => arbitrary_string_from_unstructured(u),
        4 => {
            let len = u.int_in_range(0usize..=MAX_COLLECTION)?;
            let mut items = Vec::with_capacity(len);
            for _ in 0..len {
                items.push(arbitrary_json_value(u, depth + 1)?);
            }
            Ok(Value::Array(items))
        }
        5 => {
            let len = u.int_in_range(0usize..=MAX_COLLECTION)?;
            let mut map = serde_json::Map::with_capacity(len);
            for _ in 0..len {
                let key_len = u.int_in_range(0usize..=64)?;
                let key_bytes = take_raw_bytes(u, key_len)?;
                let key = String::from_utf8_lossy(&key_bytes).into_owned();
                let val = arbitrary_json_value(u, depth + 1)?;
                map.insert(key, val);
            }
            Ok(Value::Object(map))
        }
        7 => {
            // Tower of single-element arrays (deep nesting path).
            let depth_extra = u.int_in_range(1usize..=18)?;
            let mut v = arbitrary_json_value(u, depth.saturating_add(1))?;
            for _ in 1..depth_extra {
                v = Value::Array(vec![v]);
            }
            Ok(v)
        }
        8 => arbitrary_number_from_unstructured(u),
        9 => Ok(Value::Array(vec![])),
        10 => Ok(Value::Object(serde_json::Map::new())),
        11 => arbitrary_string_from_unstructured(u),
        _ => Ok(Value::Bool(u.arbitrary()?)),
    }
}

fn trace_fingerprint(manifest: &tarka_core::evidence::EvidenceManifest) -> Vec<(String, String, bool)> {
    let Some(trace) = manifest.trace.as_ref() else {
        return Vec::new();
    };
    trace
        .steps
        .iter()
        .map(|s| (s.rule_id.clone(), s.logic_operator.clone(), s.result))
        .collect()
}

fuzz_target!(|data: &[u8]| {
    let mut u = Unstructured::new(data);
    let payload = match arbitrary_json_value(&mut u, 0) {
        Ok(v) => v,
        Err(_) => Value::Null,
    };

    let rule = fixed_rule();
    let mut eval_a =
        Evaluator::new(rule.clone(), TraceContext::new(), MockExternal::default(), "fuzz-target");
    let mut eval_b =
        Evaluator::new(rule, TraceContext::new(), MockExternal::default(), "fuzz-target");

    let (dec_a, out_a) = eval_a.evaluate(&payload);
    let (dec_b, out_b) = eval_b.evaluate(&payload);

    assert_eq!(
        dec_a, dec_b,
        "non-deterministic boolean decision for identical payload"
    );

    match (&out_a, &out_b) {
        (Ok(m_a), Ok(m_b)) => {
            assert_eq!(
                trace_fingerprint(m_a),
                trace_fingerprint(m_b),
                "trace fingerprint mismatch"
            );
        }
        (Err(p_a), Err(p_b)) => {
            assert_eq!(
                p_a.failing_rule_id, p_b.failing_rule_id,
                "non-deterministic fatal rule id"
            );
        }
        _ => panic!("outcome mismatch: Ok vs Err between twin evaluations"),
    }
});
