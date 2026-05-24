//! Serializable batch replay evaluation scorecard models.

use std::collections::BTreeSet;
use std::fmt::Write as _;
use std::time::Duration;

use serde::{Deserialize, Serialize};
use tarka_core::evidence::Step;
use thiserror::Error;

/// Lock-free mergeable counters accumulated during parallel batch replay.
#[derive(Debug, Clone, PartialEq, Eq, Default, Serialize, Deserialize)]
pub struct ScorecardCounterMatrix {
    pub manifests_consumed: u64,
    pub total_evaluated: u64,
    pub decision_match_count: u64,
    pub step_parity_count: u64,
    pub status_match: u64,
    pub status_mismatch: u64,
    pub status_partial: u64,
    pub status_error: u64,
    pub true_positive: u64,
    pub false_positive: u64,
    pub true_negative: u64,
    pub false_negative: u64,
    pub ground_truth_labeled: u64,
    pub historical_ground_truth_tp: u64,
    pub historical_ground_truth_fp: u64,
    pub historical_ground_truth_tn: u64,
    pub historical_ground_truth_fn: u64,
    pub replay_ground_truth_tp: u64,
    pub replay_ground_truth_fp: u64,
    pub replay_ground_truth_tn: u64,
    pub replay_ground_truth_fn: u64,
}

impl ScorecardCounterMatrix {
    fn absorb_record(&mut self, record: &EvaluatedManifestRecord) {
        self.manifests_consumed += 1;

        if record.new_decision.is_some() {
            self.total_evaluated += 1;
            if record.decision_match {
                self.decision_match_count += 1;
            }
            if record.step_parity {
                self.step_parity_count += 1;
            }
        }

        match classify_manifest_record(record) {
            ManifestRunClass::Match => self.status_match += 1,
            ManifestRunClass::Mismatch => self.status_mismatch += 1,
            ManifestRunClass::Partial => self.status_partial += 1,
            ManifestRunClass::Error => self.status_error += 1,
        }

        if let (Some(audit), Some(replay)) = (record.historical_decision, record.new_decision) {
            match (audit, replay) {
                (true, true) => self.true_positive += 1,
                (false, true) => self.false_positive += 1,
                (false, false) => self.true_negative += 1,
                (true, false) => self.false_negative += 1,
            }
        }

        if let Some(ground_truth_fraud) = record.ground_truth_fraud {
            self.ground_truth_labeled += 1;
            if let Some(historical) = record.historical_decision {
                absorb_prediction_vs_ground_truth(
                    historical,
                    ground_truth_fraud,
                    &mut self.historical_ground_truth_tp,
                    &mut self.historical_ground_truth_fp,
                    &mut self.historical_ground_truth_tn,
                    &mut self.historical_ground_truth_fn,
                );
            }
            if let Some(replay) = record.new_decision {
                absorb_prediction_vs_ground_truth(
                    replay,
                    ground_truth_fraud,
                    &mut self.replay_ground_truth_tp,
                    &mut self.replay_ground_truth_fp,
                    &mut self.replay_ground_truth_tn,
                    &mut self.replay_ground_truth_fn,
                );
            }
        }
    }

    fn merge(&mut self, other: Self) {
        self.manifests_consumed += other.manifests_consumed;
        self.total_evaluated += other.total_evaluated;
        self.decision_match_count += other.decision_match_count;
        self.step_parity_count += other.step_parity_count;
        self.status_match += other.status_match;
        self.status_mismatch += other.status_mismatch;
        self.status_partial += other.status_partial;
        self.status_error += other.status_error;
        self.true_positive += other.true_positive;
        self.false_positive += other.false_positive;
        self.true_negative += other.true_negative;
        self.false_negative += other.false_negative;
        self.ground_truth_labeled += other.ground_truth_labeled;
        self.historical_ground_truth_tp += other.historical_ground_truth_tp;
        self.historical_ground_truth_fp += other.historical_ground_truth_fp;
        self.historical_ground_truth_tn += other.historical_ground_truth_tn;
        self.historical_ground_truth_fn += other.historical_ground_truth_fn;
        self.replay_ground_truth_tp += other.replay_ground_truth_tp;
        self.replay_ground_truth_fp += other.replay_ground_truth_fp;
        self.replay_ground_truth_tn += other.replay_ground_truth_tn;
        self.replay_ground_truth_fn += other.replay_ground_truth_fn;
    }
}

fn absorb_prediction_vs_ground_truth(
    predicted_fraud: bool,
    ground_truth_fraud: bool,
    tp: &mut u64,
    fp: &mut u64,
    tn: &mut u64,
    fn_count: &mut u64,
) {
    match (predicted_fraud, ground_truth_fraud) {
        (true, true) => *tp += 1,
        (true, false) => *fp += 1,
        (false, false) => *tn += 1,
        (false, true) => *fn_count += 1,
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum ManifestRunClass {
    Match,
    Mismatch,
    Partial,
    Error,
}

fn classify_manifest_record(record: &EvaluatedManifestRecord) -> ManifestRunClass {
    if record.new_decision.is_none() {
        return ManifestRunClass::Error;
    }
    if record.error.is_some() {
        return ManifestRunClass::Partial;
    }
    if record.decision_match && record.step_parity {
        ManifestRunClass::Match
    } else {
        ManifestRunClass::Mismatch
    }
}

/// Per-thread batch replay scorecard accumulator; merge with [`ScorecardCollector::merge`] after parallel work.
#[derive(Debug, Default)]
pub struct ScorecardCollector {
    counters: ScorecardCounterMatrix,
    mismatches: Vec<MismatchDetail>,
}

impl ScorecardCollector {
    pub fn new() -> Self {
        Self::default()
    }

    pub fn counters(&self) -> &ScorecardCounterMatrix {
        &self.counters
    }

    pub fn mismatches(&self) -> &[MismatchDetail] {
        &self.mismatches
    }

    /// Record one manifest evaluation into the local counter matrix (no locks; safe inside rayon fold shards).
    pub fn record_evaluated(&mut self, record: EvaluatedManifestRecord) {
        if is_mismatch(&record) {
            self.mismatches.push((&record).into());
        }
        self.counters.absorb_record(&record);
    }

    /// Combine shard-local collectors after parallel fold (lock-free tree reduction).
    pub fn merge(mut self, other: Self) -> Self {
        self.counters.merge(other.counters);
        self.mismatches.extend(other.mismatches);
        self
    }

    /// Finalize the global run counters and mismatch list into a serializable scorecard.
    ///
    /// ``worker_elapsed`` must cover only parallel replay worker time (not ClickHouse prefetch).
    /// Throughput is derived via [`compute_transactions_per_second`].
    pub fn into_replay_scorecard(
        self,
        execution_time_ms: u64,
        worker_elapsed: Duration,
    ) -> ReplayScorecard {
        let (false_positive_rate_delta, precision_delta, recall_delta) =
            compute_adjustments_from_matrix(&self.counters);

        ReplayScorecard {
            total_evaluated: self.counters.total_evaluated,
            decision_match_count: self.counters.decision_match_count,
            step_parity_count: self.counters.step_parity_count,
            mismatches: self.mismatches,
            false_positive_rate_delta,
            precision_delta,
            recall_delta,
            execution_time_ms,
            transactions_per_second: compute_transactions_per_second(
                self.counters.total_evaluated,
                worker_elapsed,
            ),
        }
    }
}

/// Average replay throughput (manifests with a replay decision per wall-second of worker time).
pub fn compute_transactions_per_second(total_evaluated: u64, worker_elapsed: Duration) -> f64 {
    if total_evaluated == 0 {
        return 0.0;
    }
    let secs = worker_elapsed.as_secs_f64();
    if secs <= 0.0 {
        return 0.0;
    }
    finite_or_zero(total_evaluated as f64 / secs)
}

/// Summary of the supplementary ClickHouse ground-truth cross-reference block.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct GroundTruthCrossrefSummary {
    pub labels_table: String,
    pub transaction_ids_processed: u64,
    pub ground_truth_labels_matched: u64,
}

/// Aggregate replay evaluation report for a tenant/window batch.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct ReplayScorecard {
    pub total_evaluated: u64,
    pub decision_match_count: u64,
    pub step_parity_count: u64,
    pub mismatches: Vec<MismatchDetail>,
    pub false_positive_rate_delta: f64,
    pub precision_delta: f64,
    pub recall_delta: f64,
    pub execution_time_ms: u64,
    /// Manifest replay throughput over the parallel worker loop (`total_evaluated` / worker seconds).
    pub transactions_per_second: f64,
}

/// Per-manifest divergence captured when replay does not fully match audit evidence.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct MismatchDetail {
    pub manifest_id: String,
    pub historical_decision: Option<bool>,
    pub new_decision: Option<bool>,
    pub diverged_rules: Vec<String>,
    pub diff_trace: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub error: Option<String>,
}

/// Inputs for [`MismatchCollector::collect`].
#[derive(Debug, Clone, PartialEq)]
pub struct TraceMismatchCapture {
    pub manifest_id: String,
    pub historical_decision: Option<bool>,
    pub new_decision: Option<bool>,
    pub historical_steps: Vec<Step>,
    pub new_steps: Vec<Step>,
    pub compare_otel: bool,
    pub error: Option<String>,
}

/// Collects structured mismatch evidence from historical vs replay trace comparison.
#[derive(Debug, Default)]
pub struct MismatchCollector;

impl MismatchCollector {
    /// Build a [`MismatchDetail`] from production trace evidence and a local replay run.
    pub fn collect(input: TraceMismatchCapture) -> MismatchDetail {
        if let Some(err) = input.error.as_deref() {
            return MismatchDetail {
                manifest_id: input.manifest_id,
                historical_decision: input.historical_decision,
                new_decision: input.new_decision,
                diverged_rules: Vec::new(),
                diff_trace: format!("evaluation error before trace parity: {err}"),
                error: Some(err.to_string()),
            };
        }

        let analysis = analyze_trace_divergence(
            &input.historical_steps,
            &input.new_steps,
            input.compare_otel,
        );

        let diff_trace = render_diff_trace(
            input.historical_decision,
            input.new_decision,
            &analysis,
            &input.historical_steps,
            &input.new_steps,
            input.compare_otel,
        );

        MismatchDetail {
            manifest_id: input.manifest_id,
            historical_decision: input.historical_decision,
            new_decision: input.new_decision,
            diverged_rules: analysis.diverged_rules,
            diff_trace,
            error: None,
        }
    }
}

/// Minimal per-row inputs for scorecard aggregation (decoupled from replay worker enums).
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct EvaluatedManifestRecord {
    pub manifest_id: String,
    pub historical_decision: Option<bool>,
    pub new_decision: Option<bool>,
    pub decision_match: bool,
    pub step_parity: bool,
    pub transaction_id: Option<String>,
    pub ground_truth_fraud: Option<bool>,
    pub diverged_rules: Vec<String>,
    pub diff_trace: String,
    pub error: Option<String>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
struct TraceDivergenceAnalysis {
    diverged_rules: Vec<String>,
    pivot: Option<PivotDetail>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
struct PivotDetail {
    step_index: usize,
    rule_id: String,
    pivot_parameter: String,
    summary: String,
}

#[derive(Debug, Error, PartialEq, Eq)]
pub enum ScorecardError {
    #[error("scorecard JSON serialization failed: {0}")]
    Serialize(String),
}

impl ReplayScorecard {
    /// Build a scorecard from per-manifest evaluation records and measured wall time.
    pub fn from_evaluated_records(
        records: &[EvaluatedManifestRecord],
        execution_time_ms: u64,
    ) -> Self {
        let worker_elapsed = Duration::from_millis(execution_time_ms);
        let mut collector = ScorecardCollector::new();
        for record in records {
            collector.record_evaluated(record.clone());
        }
        collector.into_replay_scorecard(execution_time_ms, worker_elapsed)
    }

    /// Serialize to compact JSON (single line, stable field order via serde).
    pub fn to_json(&self) -> Result<String, ScorecardError> {
        serde_json::to_string(self).map_err(|e| ScorecardError::Serialize(e.to_string()))
    }

    /// Serialize to pretty-printed JSON for operator-facing scorecard artifacts.
    pub fn to_json_pretty(&self) -> Result<String, ScorecardError> {
        serde_json::to_string_pretty(self)
            .map_err(|e| ScorecardError::Serialize(e.to_string()))
    }
}

impl From<&EvaluatedManifestRecord> for MismatchDetail {
    fn from(record: &EvaluatedManifestRecord) -> Self {
        if record.error.is_some() || record.diff_trace.is_empty() {
            return MismatchCollector::collect(TraceMismatchCapture {
                manifest_id: record.manifest_id.clone(),
                historical_decision: record.historical_decision,
                new_decision: record.new_decision,
                historical_steps: Vec::new(),
                new_steps: Vec::new(),
                compare_otel: false,
                error: record.error.clone(),
            });
        }

        Self {
            manifest_id: record.manifest_id.clone(),
            historical_decision: record.historical_decision,
            new_decision: record.new_decision,
            diverged_rules: record.diverged_rules.clone(),
            diff_trace: record.diff_trace.clone(),
            error: record.error.clone(),
        }
    }
}

fn is_mismatch(record: &EvaluatedManifestRecord) -> bool {
    if record.error.is_some() {
        return true;
    }
    if record.new_decision.is_none() {
        return true;
    }
    !record.decision_match || !record.step_parity
}

fn analyze_trace_divergence(
    historical_steps: &[Step],
    new_steps: &[Step],
    compare_otel: bool,
) -> TraceDivergenceAnalysis {
    let mut diverged_rules = Vec::new();
    let mut pivot = None;
    let max = historical_steps.len().max(new_steps.len());

    for index in 0..max {
        let historical = historical_steps.get(index);
        let new = new_steps.get(index);

        let (diverged, step_pivot) = match (historical, new) {
            (Some(h), Some(n)) => {
                if steps_equivalent(h, n, compare_otel) {
                    (false, None)
                } else {
                    (
                        true,
                        Some(build_pivot_detail(index, h, n, compare_otel)),
                    )
                }
            }
            (Some(h), None) => (
                true,
                Some(PivotDetail {
                    step_index: index,
                    rule_id: h.rule_id.clone(),
                    pivot_parameter: "trace.length".into(),
                    summary: format!(
                        "step[{index}] rule_id={}: missing in replay (historical had {} steps, replay ended at {index})",
                        h.rule_id,
                        historical_steps.len()
                    ),
                }),
            ),
            (None, Some(n)) => (
                true,
                Some(PivotDetail {
                    step_index: index,
                    rule_id: n.rule_id.clone(),
                    pivot_parameter: "trace.length".into(),
                    summary: format!(
                        "step[{index}] rule_id={}: extra in replay (historical had {} steps, replay has {})",
                        n.rule_id,
                        historical_steps.len(),
                        new_steps.len()
                    ),
                }),
            ),
            (None, None) => (false, None),
        };

        if diverged {
            let rule_id = historical
                .map(|s| s.rule_id.as_str())
                .or_else(|| new.map(|s| s.rule_id.as_str()))
                .unwrap_or("unknown")
                .to_string();
            if !diverged_rules.iter().any(|existing| existing == &rule_id) {
                diverged_rules.push(rule_id);
            }
            if pivot.is_none() {
                pivot = step_pivot;
            }
        }
    }

    TraceDivergenceAnalysis {
        diverged_rules,
        pivot,
    }
}

fn build_pivot_detail(
    step_index: usize,
    historical: &Step,
    new: &Step,
    compare_otel: bool,
) -> PivotDetail {
    let pivot_parameter = identify_pivot_parameter(historical, new, compare_otel);
    let summary = format_step_divergence(step_index, historical, new, compare_otel, &pivot_parameter);

    PivotDetail {
        step_index,
        rule_id: historical.rule_id.clone(),
        pivot_parameter,
        summary,
    }
}

fn identify_pivot_parameter(historical: &Step, new: &Step, compare_otel: bool) -> String {
    if historical.rule_id != new.rule_id {
        return format!(
            "rule_id (historical={} new={})",
            historical.rule_id, new.rule_id
        );
    }
    if historical.logic_operator != new.logic_operator {
        return format!(
            "logic_operator (historical={} new={})",
            historical.logic_operator, new.logic_operator
        );
    }
    if historical.result != new.result {
        if let Some(parameter) = first_state_snapshot_delta(historical, new) {
            return parameter;
        }
        if historical.operands != new.operands {
            return format!(
                "operands (historical={:?} new={:?})",
                historical.operands, new.operands
            );
        }
        return format!(
            "result (historical={} new={})",
            historical.result, new.result
        );
    }
    if historical.operands != new.operands {
        return format!(
            "operands (historical={:?} new={:?})",
            historical.operands, new.operands
        );
    }
    if let Some(parameter) = first_state_snapshot_delta(historical, new) {
        return parameter;
    }
    if compare_otel && historical.otel_trace_id != new.otel_trace_id {
        return format!(
            "otel_trace_id (historical={} new={})",
            historical.otel_trace_id, new.otel_trace_id
        );
    }
    "unknown".into()
}

fn first_state_snapshot_delta(historical: &Step, new: &Step) -> Option<String> {
    let keys: BTreeSet<&str> = historical
        .state_snapshot
        .keys()
        .map(String::as_str)
        .chain(new.state_snapshot.keys().map(String::as_str))
        .collect();

    for key in keys {
        let historical_value = historical.state_snapshot.get(key);
        let new_value = new.state_snapshot.get(key);
        if historical_value != new_value {
            return Some(format!(
                "{key} (historical={} new={})",
                historical_value.unwrap_or(&"<missing>".into()),
                new_value.unwrap_or(&"<missing>".into())
            ));
        }
    }
    None
}

fn format_step_divergence(
    step_index: usize,
    historical: &Step,
    new: &Step,
    compare_otel: bool,
    pivot_parameter: &str,
) -> String {
    let mut out = format!(
        "step[{step_index}] rule_id={}: pivot parameter={pivot_parameter}; historical result={} new result={}",
        historical.rule_id, historical.result, new.result
    );

    if historical.rule_id != new.rule_id {
        let _ = write!(
            out,
            "; rule_id historical={} new={}",
            historical.rule_id, new.rule_id
        );
    }
    if historical.logic_operator != new.logic_operator {
        let _ = write!(
            out,
            "; logic_operator historical={} new={}",
            historical.logic_operator, new.logic_operator
        );
    }
    if historical.operands != new.operands {
        let _ = write!(
            out,
            "; operands historical={:?} new={:?}",
            historical.operands, new.operands
        );
    }

    let snapshot_delta = format_state_snapshot_delta(historical, new);
    if !snapshot_delta.is_empty() {
        let _ = write!(out, "; state_snapshot delta: {snapshot_delta}");
    }

    if compare_otel && historical.otel_trace_id != new.otel_trace_id {
        let _ = write!(
            out,
            "; otel_trace_id historical={} new={}",
            historical.otel_trace_id, new.otel_trace_id
        );
    }

    out
}

fn format_state_snapshot_delta(historical: &Step, new: &Step) -> String {
    let keys: BTreeSet<&str> = historical
        .state_snapshot
        .keys()
        .map(String::as_str)
        .chain(new.state_snapshot.keys().map(String::as_str))
        .collect();

    let mut parts = Vec::new();
    for key in keys {
        let historical_value = historical.state_snapshot.get(key);
        let new_value = new.state_snapshot.get(key);
        if historical_value != new_value {
            parts.push(format!(
                "{key}: historical={} new={}",
                historical_value.unwrap_or(&"<missing>".into()),
                new_value.unwrap_or(&"<missing>".into())
            ));
        }
    }
    parts.join(", ")
}

fn render_diff_trace(
    historical_decision: Option<bool>,
    new_decision: Option<bool>,
    analysis: &TraceDivergenceAnalysis,
    historical_steps: &[Step],
    new_steps: &[Step],
    compare_otel: bool,
) -> String {
    let mut out = String::new();
    writeln!(out, "=== rule evaluation mismatch trace ===").unwrap();

    match (historical_decision, new_decision) {
        (Some(h), Some(n)) if h != n => {
            writeln!(
                out,
                "final_decision: historical={h} new={n} (decision pivot before trace parity)"
            )
            .unwrap();
        }
        (Some(h), Some(n)) => {
            writeln!(out, "final_decision: historical={h} new={n}").unwrap();
        }
        _ => {
            writeln!(out, "final_decision: historical={historical_decision:?} new={new_decision:?}")
                .unwrap();
        }
    }

    if let Some(pivot) = &analysis.pivot {
        writeln!(out, "pivot: {}", pivot.summary).unwrap();
    } else if historical_steps.is_empty() && new_steps.is_empty() {
        writeln!(out, "pivot: no trace steps available for comparison").unwrap();
    } else {
        writeln!(out, "pivot: trace steps matched; divergence is outside leaf-step parity")
            .unwrap();
    }

    if analysis.diverged_rules.is_empty() {
        writeln!(out, "diverged_rules: none").unwrap();
    } else {
        writeln!(out, "diverged_rules: {}", analysis.diverged_rules.join(", ")).unwrap();
    }

    let max = historical_steps.len().max(new_steps.len());
    for index in 0..max {
        let historical = historical_steps.get(index);
        let new = new_steps.get(index);
        match (historical, new) {
            (Some(h), Some(n)) if !steps_equivalent(h, n, compare_otel) => {
                let parameter = identify_pivot_parameter(h, n, compare_otel);
                writeln!(
                    out,
                    "  {}",
                    format_step_divergence(index, h, n, compare_otel, &parameter)
                )
                .unwrap();
            }
            (Some(h), None) => {
                writeln!(
                    out,
                    "  step[{index}] missing in replay: rule_id={} result={}",
                    h.rule_id, h.result
                )
                .unwrap();
            }
            (None, Some(n)) => {
                writeln!(
                    out,
                    "  step[{index}] extra in replay: rule_id={} result={}",
                    n.rule_id, n.result
                )
                .unwrap();
            }
            _ => {}
        }
    }

    out
}

fn steps_equivalent(historical: &Step, new: &Step, compare_otel: bool) -> bool {
    historical.rule_id == new.rule_id
        && historical.logic_operator == new.logic_operator
        && historical.result == new.result
        && historical.operands == new.operands
        && historical.state_snapshot == new.state_snapshot
        && (!compare_otel || historical.otel_trace_id == new.otel_trace_id)
}

/// Compare replay decisions against captured audit decisions (audit = reference).
fn compute_adjustments_from_matrix(matrix: &ScorecardCounterMatrix) -> (f64, f64, f64) {
    if matrix.ground_truth_labeled > 0 {
        let historical = classifier_metrics(
            matrix.historical_ground_truth_tp,
            matrix.historical_ground_truth_fp,
            matrix.historical_ground_truth_tn,
            matrix.historical_ground_truth_fn,
        );
        let replay = classifier_metrics(
            matrix.replay_ground_truth_tp,
            matrix.replay_ground_truth_fp,
            matrix.replay_ground_truth_tn,
            matrix.replay_ground_truth_fn,
        );
        return sanitize_adjustments(
            replay.precision - historical.precision,
            replay.recall - historical.recall,
            replay.false_positive_rate - historical.false_positive_rate,
        );
    }

    let (false_positive_rate_delta, precision_delta) = compute_audit_reference_deltas(matrix);
    (false_positive_rate_delta, precision_delta, 0.0)
}

fn compute_audit_reference_deltas(matrix: &ScorecardCounterMatrix) -> (f64, f64) {
    let fp = matrix.false_positive;
    let tn = matrix.true_negative;
    let tp = matrix.true_positive;

    let audit_fpr = 0.0_f64;
    let replay_fpr = if fp + tn > 0 {
        fp as f64 / (fp + tn) as f64
    } else {
        0.0
    };
    let false_positive_rate_delta = replay_fpr - audit_fpr;

    let audit_precision = 1.0;
    let replay_precision = if tp + fp > 0 {
        tp as f64 / (tp + fp) as f64
    } else {
        0.0
    };
    let precision_delta = replay_precision - audit_precision;

    sanitize_metric(false_positive_rate_delta, precision_delta)
}

#[derive(Debug, Clone, Copy, PartialEq)]
struct ClassifierMetrics {
    precision: f64,
    recall: f64,
    false_positive_rate: f64,
}

fn classifier_metrics(tp: u64, fp: u64, tn: u64, fn_count: u64) -> ClassifierMetrics {
    ClassifierMetrics {
        precision: if tp + fp > 0 {
            tp as f64 / (tp + fp) as f64
        } else {
            0.0
        },
        recall: if tp + fn_count > 0 {
            tp as f64 / (tp + fn_count) as f64
        } else {
            0.0
        },
        false_positive_rate: if fp + tn > 0 {
            fp as f64 / (fp + tn) as f64
        } else {
            0.0
        },
    }
}

fn sanitize_adjustments(precision_delta: f64, recall_delta: f64, fpr_delta: f64) -> (f64, f64, f64) {
    (
        finite_or_zero(fpr_delta),
        finite_or_zero(precision_delta),
        finite_or_zero(recall_delta),
    )
}

fn sanitize_metric(false_positive_rate_delta: f64, precision_delta: f64) -> (f64, f64) {
    (
        finite_or_zero(false_positive_rate_delta),
        finite_or_zero(precision_delta),
    )
}

fn finite_or_zero(value: f64) -> f64 {
    if value.is_finite() {
        value
    } else {
        0.0
    }
}

/// Envelope written to `--scorecard-output` (metadata + nested replay metrics).
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct BatchReplayScorecardDocument {
    pub schema: String,
    pub tenant_id: String,
    pub since: String,
    pub until: String,
    pub since_unix_ns: i64,
    pub until_unix_ns: i64,
    pub concurrency: usize,
    pub manifest_count: u64,
    pub max_batch_pull_cap: usize,
    pub run_counters: ScorecardCounterMatrix,
    pub ground_truth_crossref: GroundTruthCrossrefSummary,
    #[serde(flatten)]
    pub replay: ReplayScorecard,
}

impl BatchReplayScorecardDocument {
    pub fn to_json_pretty(&self) -> Result<String, ScorecardError> {
        serde_json::to_string_pretty(self)
            .map_err(|e| ScorecardError::Serialize(e.to_string()))
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn step(
        rule_id: &str,
        op: &str,
        operands: &[&str],
        result: bool,
        snapshot: &[(&str, &str)],
    ) -> Step {
        Step {
            rule_id: rule_id.into(),
            logic_operator: op.into(),
            operands: operands.iter().map(|s| (*s).into()).collect(),
            result,
            state_snapshot: snapshot
                .iter()
                .map(|(k, v)| (k.to_string(), v.to_string()))
                .collect(),
            otel_trace_id: String::new(),
        }
    }

    fn record(
        id: &str,
        historical: Option<bool>,
        new: Option<bool>,
        decision_match: bool,
        step_parity: bool,
        diverged_rules: Vec<&str>,
        diff_trace: &str,
        error: Option<&str>,
    ) -> EvaluatedManifestRecord {
        EvaluatedManifestRecord {
            manifest_id: id.into(),
            historical_decision: historical,
            new_decision: new,
            decision_match,
            step_parity,
            transaction_id: None,
            ground_truth_fraud: None,
            diverged_rules: diverged_rules.into_iter().map(str::to_string).collect(),
            diff_trace: diff_trace.into(),
            error: error.map(str::to_string),
        }
    }

    fn record_with_ground_truth(
        id: &str,
        historical: Option<bool>,
        new: Option<bool>,
        ground_truth_fraud: bool,
    ) -> EvaluatedManifestRecord {
        EvaluatedManifestRecord {
            manifest_id: id.into(),
            historical_decision: historical,
            new_decision: new,
            decision_match: historical == new,
            step_parity: historical == new,
            transaction_id: Some(format!("tx-{id}")),
            ground_truth_fraud: Some(ground_truth_fraud),
            diverged_rules: Vec::new(),
            diff_trace: String::new(),
            error: None,
        }
    }

    #[test]
    fn collector_captures_diverged_rules_and_pivot_parameter() {
        let historical = vec![step(
            "velocity_ip",
            "COMPARE",
            &["amount", "threshold"],
            true,
            &[("compare.threshold", "100"), ("amount", "1250")],
        )];
        let new = vec![step(
            "velocity_ip",
            "COMPARE",
            &["amount", "threshold"],
            false,
            &[("compare.threshold", "200"), ("amount", "1250")],
        )];

        let detail = MismatchCollector::collect(TraceMismatchCapture {
            manifest_id: "m-1".into(),
            historical_decision: Some(true),
            new_decision: Some(false),
            historical_steps: historical,
            new_steps: new,
            compare_otel: false,
            error: None,
        });

        assert_eq!(detail.manifest_id, "m-1");
        assert_eq!(detail.historical_decision, Some(true));
        assert_eq!(detail.new_decision, Some(false));
        assert_eq!(detail.diverged_rules, vec!["velocity_ip"]);
        assert!(detail.diff_trace.contains("pivot parameter=compare.threshold"));
        assert!(detail.diff_trace.contains("historical result=true new result=false"));
        assert!(detail.error.is_none());
    }

    #[test]
    fn collector_records_missing_replay_step_as_trace_length_pivot() {
        let historical = vec![
            step("rule_a", "AND", &[], true, &[]),
            step("rule_b", "COMPARE", &["x"], false, &[]),
        ];
        let new = vec![step("rule_a", "AND", &[], true, &[])];

        let detail = MismatchCollector::collect(TraceMismatchCapture {
            manifest_id: "m-2".into(),
            historical_decision: Some(false),
            new_decision: Some(true),
            historical_steps: historical,
            new_steps: new,
            compare_otel: false,
            error: None,
        });

        assert_eq!(detail.diverged_rules, vec!["rule_b"]);
        assert!(detail.diff_trace.contains("missing in replay"));
    }

    #[test]
    fn replay_scorecard_serializes_mismatch_detail_fields() {
        let scorecard = ReplayScorecard {
            total_evaluated: 1,
            decision_match_count: 0,
            step_parity_count: 0,
            mismatches: vec![MismatchDetail {
                manifest_id: "m-2".into(),
                historical_decision: Some(true),
                new_decision: Some(false),
                diverged_rules: vec!["velocity_ip".into()],
                diff_trace: "pivot parameter=amount".into(),
                error: None,
            }],
            false_positive_rate_delta: 0.25,
            precision_delta: -0.5,
            recall_delta: 0.0,
            execution_time_ms: 42,
            transactions_per_second: 0.0,
        };

        let json = scorecard.to_json_pretty().expect("serialize");
        assert!(json.contains("\"historical_decision\": true"));
        assert!(json.contains("\"new_decision\": false"));
        assert!(json.contains("\"diverged_rules\""));
        assert!(json.contains("\"diff_trace\""));
        assert!(json.contains("\"transactions_per_second\""));
    }

    #[test]
    fn from_evaluated_records_computes_metrics() {
        let records = vec![
            record("a", Some(true), Some(true), true, true, vec![], "", None),
            record(
                "b",
                Some(false),
                Some(true),
                false,
                true,
                vec!["velocity_ip"],
                "pivot parameter=amount",
                None,
            ),
            record(
                "c",
                Some(false),
                Some(false),
                true,
                false,
                vec!["rule_c"],
                "pivot parameter=operands",
                None,
            ),
        ];

        let scorecard = ReplayScorecard::from_evaluated_records(&records, 100);
        assert_eq!(scorecard.total_evaluated, 3);
        assert_eq!(scorecard.decision_match_count, 2);
        assert_eq!(scorecard.step_parity_count, 2);
        assert_eq!(scorecard.mismatches.len(), 2);
        assert_eq!(scorecard.mismatches[0].diverged_rules, vec!["velocity_ip"]);
        assert!((scorecard.false_positive_rate_delta - 0.5).abs() < f64::EPSILON);
        assert!((scorecard.transactions_per_second - 30.0).abs() < f64::EPSILON);
    }

    #[test]
    fn compute_transactions_per_second_uses_worker_elapsed() {
        assert_eq!(
            compute_transactions_per_second(100, Duration::from_secs(2)),
            50.0
        );
        assert_eq!(compute_transactions_per_second(0, Duration::from_secs(1)), 0.0);
        assert_eq!(compute_transactions_per_second(10, Duration::ZERO), 0.0);
    }

    #[test]
    fn ground_truth_labels_drive_precision_recall_and_fpr_adjustments() {
        let mut collector = ScorecardCollector::new();
        collector.record_evaluated(record_with_ground_truth(
            "a",
            Some(true),
            Some(true),
            true,
        ));
        collector.record_evaluated(record_with_ground_truth(
            "b",
            Some(false),
            Some(false),
            true,
        ));
        collector.record_evaluated(record_with_ground_truth(
            "c",
            Some(false),
            Some(true),
            false,
        ));

        let scorecard = collector.into_replay_scorecard(10, Duration::from_millis(10));
        assert_eq!(scorecard.recall_delta, 0.0);
        assert!((scorecard.precision_delta - (-0.5)).abs() < f64::EPSILON);
        assert!((scorecard.false_positive_rate_delta - 1.0).abs() < f64::EPSILON);
    }

    #[test]
    fn collector_merge_accumulates_counter_matrix() {
        let mut shard_a = ScorecardCollector::new();
        shard_a.record_evaluated(record(
            "a",
            Some(true),
            Some(true),
            true,
            true,
            vec![],
            "",
            None,
        ));

        let mut shard_b = ScorecardCollector::new();
        shard_b.record_evaluated(record(
            "b",
            Some(false),
            Some(true),
            false,
            true,
            vec!["velocity_ip"],
            "pivot parameter=amount",
            None,
        ));

        let merged = shard_a.merge(shard_b);
        assert_eq!(merged.counters().manifests_consumed, 2);
        assert_eq!(merged.counters().total_evaluated, 2);
        assert_eq!(merged.counters().decision_match_count, 1);
        assert_eq!(merged.counters().status_match, 1);
        assert_eq!(merged.counters().status_mismatch, 1);
        assert_eq!(merged.counters().false_positive, 1);
        assert_eq!(merged.mismatches().len(), 1);

        let scorecard = merged.into_replay_scorecard(50, Duration::from_millis(50));
        assert_eq!(scorecard.total_evaluated, 2);
        assert!((scorecard.false_positive_rate_delta - 1.0).abs() < f64::EPSILON);
    }

    #[test]
    fn batch_document_flattens_replay_scorecard_fields() {
        let doc = BatchReplayScorecardDocument {
            schema: "tarka.batch_replay_scorecard.v1".into(),
            tenant_id: "tenant-a".into(),
            since: "2026-05-01T00:00:00Z".into(),
            until: "2026-05-02T00:00:00Z".into(),
            since_unix_ns: 1,
            until_unix_ns: 2,
            concurrency: 4,
            manifest_count: 1,
            max_batch_pull_cap: 50_000,
            run_counters: ScorecardCounterMatrix {
                manifests_consumed: 1,
                total_evaluated: 1,
                decision_match_count: 1,
                step_parity_count: 1,
                status_match: 1,
                ..ScorecardCounterMatrix::default()
            },
            ground_truth_crossref: GroundTruthCrossrefSummary {
                labels_table: "normalized_labels".into(),
                transaction_ids_processed: 1,
                ground_truth_labels_matched: 1,
            },
            replay: ReplayScorecard::from_evaluated_records(
                &[record("x", Some(true), Some(true), true, true, vec![], "", None)],
                10,
            ),
        };

        let json = doc.to_json_pretty().expect("serialize");
        assert!(json.contains("\"schema\": \"tarka.batch_replay_scorecard.v1\""));
        assert!(json.contains("\"total_evaluated\": 1"));
        assert!(json.contains("\"run_counters\""));
        assert!(json.contains("\"status_match\": 1"));
    }

    #[test]
    fn first_state_snapshot_delta_prefers_changed_keys() {
        let historical = step("r", "REDIS", &["k"], true, &[("redis.value.raw", "10")]);
        let new = step("r", "REDIS", &["k"], true, &[("redis.value.raw", "20")]);
        let delta = first_state_snapshot_delta(&historical, &new).expect("delta");
        assert!(delta.contains("redis.value.raw"));
        assert!(delta.contains("10"));
        assert!(delta.contains("20"));
    }
}
