//! Human-readable diff between captured ClickHouse evidence and a fresh local replay manifest.

use std::fmt::Write as _;

use uuid::Uuid;

use tarka_core::evidence::{EvidenceManifest, Step};

/// Compare original leaf trace (from audit storage) with replayed [`EvidenceManifest`] trace.
pub fn format_diff_report(
    manifest_id: Uuid,
    original_decision: bool,
    original_exec_us: u64,
    original_steps: &[Step],
    replay_decision: bool,
    replay_exec_us: u64,
    replay: &EvidenceManifest,
    strict_timing: bool,
    compare_otel: bool,
) -> String {
    let replay_steps: &[Step] = replay
        .trace
        .as_ref()
        .map(|t| t.steps.as_slice())
        .unwrap_or(&[]);

    let mut out = String::new();
    writeln!(out, "=== Tarka Forensic Replay Diff Report ===").unwrap();
    writeln!(out, "manifest_id: {manifest_id}").unwrap();
    writeln!(out).unwrap();

    writeln!(out, "[final_decision]").unwrap();
    writeln!(
        out,
        "  original (ClickHouse): {}",
        fmt_bool(original_decision)
    )
    .unwrap();
    writeln!(out, "  replay (local engine): {}", fmt_bool(replay_decision)).unwrap();
    if original_decision != replay_decision {
        writeln!(
            out,
            "  *** DISCREPANCY: decision mismatch (audit replay divergence) ***"
        )
        .unwrap();
    }
    writeln!(out).unwrap();

    writeln!(out, "[total_execution_time_us]").unwrap();
    writeln!(out, "  original: {original_exec_us}").unwrap();
    writeln!(out, "  replay:   {replay_exec_us}").unwrap();
    if strict_timing && original_exec_us != replay_exec_us {
        writeln!(
            out,
            "  *** DISCREPANCY: timing differs under --strict-timing ***"
        )
        .unwrap();
    } else if !strict_timing && original_exec_us != replay_exec_us {
        writeln!(
            out,
            "  (informational: timing differs; strict timing comparison disabled)"
        )
        .unwrap();
    }
    writeln!(out).unwrap();

    writeln!(out, "[trace_steps]").unwrap();
    writeln!(
        out,
        "  original leaf steps: {}",
        original_steps.len()
    )
    .unwrap();
    writeln!(out, "  replay leaf steps:   {}", replay_steps.len()).unwrap();

    let max = original_steps.len().max(replay_steps.len());
    for i in 0..max {
        let o = original_steps.get(i);
        let r = replay_steps.get(i);
        match (o, r) {
            (Some(o), Some(r)) => {
                if leaf_step_equivalent(o, r, compare_otel) {
                    writeln!(out, "  step[{i}] OK rule_id={}", o.rule_id).unwrap();
                } else {
                    writeln!(out, "  step[{i}] *** MISMATCH ***").unwrap();
                    writeln!(out, "    original: {}", fmt_step(o, compare_otel)).unwrap();
                    writeln!(out, "    replay:   {}", fmt_step(r, compare_otel)).unwrap();
                }
            }
            (Some(o), None) => {
                writeln!(
                    out,
                    "  step[{i}] *** missing in replay *** original {}",
                    fmt_step(o, compare_otel)
                )
                .unwrap();
            }
            (None, Some(r)) => {
                writeln!(
                    out,
                    "  step[{i}] *** extra in replay *** replay {}",
                    fmt_step(r, compare_otel)
                )
                .unwrap();
            }
            (None, None) => {}
        }
    }

    out
}

fn fmt_bool(b: bool) -> &'static str {
    if b {
        "true"
    } else {
        "false"
    }
}

fn leaf_step_equivalent(orig: &Step, replay: &Step, compare_otel: bool) -> bool {
    if orig.rule_id != replay.rule_id
        || orig.logic_operator != replay.logic_operator
        || orig.result != replay.result
        || orig.operands != replay.operands
    {
        return false;
    }
    if compare_otel && orig.otel_trace_id != replay.otel_trace_id {
        return false;
    }
    true
}

fn fmt_step(s: &Step, include_otel: bool) -> String {
    if include_otel {
        format!(
            "rule_id={} op={} operands={:?} result={} otel={}",
            s.rule_id, s.logic_operator, s.operands, s.result, s.otel_trace_id
        )
    } else {
        format!(
            "rule_id={} op={} operands={:?} result={}",
            s.rule_id, s.logic_operator, s.operands, s.result
        )
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use tarka_core::evidence::{Metadata, Trace};

    fn step(rule_id: &str, op: &str, result: bool) -> Step {
        Step {
            rule_id: rule_id.into(),
            logic_operator: op.into(),
            operands: vec![],
            result,
            state_snapshot: Default::default(),
            otel_trace_id: String::new(),
        }
    }

    #[test]
    fn report_matches_when_identical() {
        let steps = vec![step("a", "COMPARE", true)];
        let replay = EvidenceManifest {
            header: None,
            input_map: None,
            trace: Some(Trace {
                steps: steps.clone(),
            }),
            metadata: Some(Metadata {
                final_decision: true,
                total_execution_time_us: 10,
            }),
            crypto_signature: None,
        };
        let r = format_diff_report(
            Uuid::nil(),
            true,
            10,
            &steps,
            true,
            10,
            &replay,
            false,
            false,
        );
        assert!(r.contains("step[0] OK"));
        assert!(!r.contains("DISCREPANCY: decision mismatch"));
    }
}
