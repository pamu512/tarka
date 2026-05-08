//! Thread-safe trace collector for rule evaluation ("black box" recorder).
//!
//! Concurrent evaluators share a single [`TraceContext`] by cloning (cheap `Arc` handle). Steps are
//! appended without a global mutex: each [`record_step`] reserves a monotonic [`sequence`](TraceStep::sequence)
//! and pushes to a lock-free [`crossbeam_queue::SegQueue`]. [`finalize`] drains the queue, sorts by
//! sequence, and hashes a canonical byte encoding with SHA-256 to produce a stable
//! [`LogicFingerprint`].
//!
//! **Finalize contract:** call [`TraceContext::finalize`] only after every concurrent producer has
//! finished (for example after joining worker threads). While producers are still running, steps may
//! still be in flight immediately before finalize.
//!
//! **Ordering:** [`TraceStep::captured_at_ms`] is wall-clock milliseconds at capture time; total order
//! for the fingerprint is defined by `sequence` when multiple steps share the same millisecond.

use crossbeam_queue::SegQueue;
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use smallvec::SmallVec;
use std::collections::BTreeMap;
use std::fmt;
use std::sync::atomic::{AtomicBool, AtomicU64, Ordering};
use std::sync::Arc;
use thiserror::Error;

use super::clock::{self, system_clock, SharedClock};

/// Default inline capacity for [`TraceStep::operands`] before spilling to the heap.
pub const DEFAULT_OPERAND_INLINE: usize = 8;

/// One evaluated rule invocation recorded in evaluation order.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct TraceStep {
    /// Monotonic position in this trace (assigned at `record_step`, stronger than wall clock alone).
    pub sequence: u64,
    /// Wall-clock instant in whole milliseconds since [`UNIX_EPOCH`] when the snapshot was taken.
    pub captured_at_ms: u64,
    pub rule_id: Box<str>,
    pub operator: Box<str>,
    pub operands: SmallVec<[Box<str>; DEFAULT_OPERAND_INLINE]>,
    pub result: bool,
    /// Immutable snapshot of in-scope variables at `captured_at_ms`.
    pub scope_snapshot: BTreeMap<Box<str>, Box<str>>,
}

/// SHA-256 digest over the canonical serialization of all [`TraceStep`] values in sequence order.
#[derive(Clone, Copy, Eq, PartialEq, Serialize, Deserialize)]
pub struct LogicFingerprint {
    pub sha256: [u8; 32],
}

impl fmt::Debug for LogicFingerprint {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "LogicFingerprint(")?;
        for b in &self.sha256 {
            write!(f, "{:02x}", b)?;
        }
        write!(f, ")")
    }
}

/// Errors from [`TraceContext::record_step`] and [`TraceContext::finalize`].
#[derive(Debug, Error)]
pub enum TraceError {
    #[error("trace has already been finalized")]
    Finalized,
}

struct Inner {
    next_sequence: AtomicU64,
    /// Mirrors queued trace steps for observability (SegQueue has no `len()`).
    queued_steps: AtomicU64,
    queue: SegQueue<TraceStep>,
    finalized: AtomicBool,
    /// OpenTelemetry W3C trace id (32 lowercase hex chars), carried onto every evidence [`crate::evidence::Step`].
    otel_trace_id: Option<String>,
    /// Wall clock for [`TraceStep::captured_at_ms`] and shared with [`super::evaluator::Evaluator`].
    clock: SharedClock,
}

/// Shared black-box trace state; clone is shallow (`Arc`).
#[derive(Clone)]
pub struct TraceContext {
    inner: Arc<Inner>,
}

impl fmt::Debug for TraceContext {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.debug_struct("TraceContext").finish_non_exhaustive()
    }
}

impl Default for TraceContext {
    fn default() -> Self {
        Self::new()
    }
}

impl TraceContext {
    /// Creates a new trace context (not yet finalized).
    pub fn new() -> Self {
        Self::with_otel_trace_id(None)
    }

    /// Creates a trace context that stamps every finalized protobuf [`crate::evidence::Step`] with `otel_trace_id`.
    pub fn with_otel_trace_id(trace_id: Option<String>) -> Self {
        Self::with_clock_and_otel(system_clock(), trace_id)
    }

    /// Full constructor: custom [`super::clock::Clock`] (e.g. [`super::clock::FixedClock`] for replay) plus optional OTEL trace id.
    pub fn with_clock_and_otel(clock: SharedClock, trace_id: Option<String>) -> Self {
        Self {
            inner: Arc::new(Inner {
                next_sequence: AtomicU64::new(0),
                queued_steps: AtomicU64::new(0),
                queue: SegQueue::new(),
                finalized: AtomicBool::new(false),
                otel_trace_id: trace_id,
                clock,
            }),
        }
    }

    /// [`SharedClock`] handle (same instance as [`super::evaluator::Evaluator::clock`] when constructed together).
    pub fn clock(&self) -> SharedClock {
        self.inner.clock.clone()
    }

    /// Returns the bound OpenTelemetry trace id for this evaluation (clone for evaluator reuse).
    pub fn otel_trace_id_cloned(&self) -> Option<String> {
        self.inner.otel_trace_id.clone()
    }

    /// Borrowed view of the trace id for manifest construction (empty/`None` ⇒ no upstream propagation).
    pub fn otel_trace_id(&self) -> Option<&str> {
        self.inner.otel_trace_id.as_deref()
    }

    /// Records one evaluation step with a snapshot of `current_scope` at the current millisecond.
    ///
    /// Safe to call concurrently from multiple threads on the same [`TraceContext`]. Ordering is
    /// preserved via an internal monotonic sequence number.
    pub fn record_step(
        &self,
        rule_id: impl AsRef<str>,
        operator: impl AsRef<str>,
        operands: impl IntoIterator<Item = impl AsRef<str>>,
        result: bool,
        current_scope: &BTreeMap<Box<str>, Box<str>>,
    ) -> Result<(), TraceError> {
        if self.inner.finalized.load(Ordering::Acquire) {
            return Err(TraceError::Finalized);
        }

        let captured_at_ms = clock::wall_clock_ms(self.inner.clock.as_ref());

        let sequence = self.inner.next_sequence.fetch_add(1, Ordering::AcqRel);

        let mut op_vec = SmallVec::new();
        for operand in operands {
            op_vec.push(operand.as_ref().to_string().into_boxed_str());
        }

        let step = TraceStep {
            sequence,
            captured_at_ms,
            rule_id: rule_id.as_ref().to_string().into_boxed_str(),
            operator: operator.as_ref().to_string().into_boxed_str(),
            operands: op_vec,
            result,
            scope_snapshot: current_scope.clone(),
        };

        self.inner.queue.push(step);

        let depth = self.inner.queued_steps.fetch_add(1, Ordering::Relaxed) + 1;
        crate::metrics_export::set_buffer_utilization_ratio(depth);
        crate::metrics_export::record_rules_evaluated(1);

        Ok(())
    }

    /// Drains all recorded steps, sorts by [`TraceStep::sequence`], and returns the SHA-256 digest of
    /// the canonical encoding. Further [`record_step`] calls fail afterward.
    ///
    /// For correct results under concurrency, ensure no [`record_step`] is in progress when this runs
    /// (typically: barrier/join all producers first).
    /// Same as [`finalize`](Self::finalize), but also returns the ordered [`TraceStep`] list used for
    /// the digest (for evidence manifests).
    pub fn finalize_with_trace(&self) -> Result<(LogicFingerprint, Vec<TraceStep>), TraceError> {
        if self
            .inner
            .finalized
            .compare_exchange(false, true, Ordering::AcqRel, Ordering::Acquire)
            .is_err()
        {
            return Err(TraceError::Finalized);
        }

        let mut steps = Vec::new();
        while let Some(step) = self.inner.queue.pop() {
            steps.push(step);
        }

        self.inner.queued_steps.store(0, Ordering::Release);
        crate::metrics_export::set_buffer_utilization_ratio(0);

        steps.sort_by_key(|s| s.sequence);

        let payload = canonical_step_payload(self.inner.otel_trace_id.as_deref(), &steps);
        let sha256: [u8; 32] = Sha256::digest(&payload).into();

        Ok((LogicFingerprint { sha256 }, steps))
    }

    pub fn finalize(&self) -> Result<LogicFingerprint, TraceError> {
        self.finalize_with_trace().map(|(fp, _)| fp)
    }
}

/// Registry of isolated [`TraceContext`] instances keyed by caller-chosen id (for example evaluation
/// correlation id). Uses [`dashmap::DashMap`] so concurrent evaluations touching **different** keys
/// do not serialize on one mutex.
#[derive(Debug, Default, Clone)]
pub struct TraceContextRegistry<K: Eq + std::hash::Hash + Clone> {
    map: Arc<dashmap::DashMap<K, TraceContext>>,
}

impl<K: Eq + std::hash::Hash + Clone> TraceContextRegistry<K> {
    pub fn new() -> Self {
        Self {
            map: Arc::new(dashmap::DashMap::new()),
        }
    }

    pub fn get_or_insert(&self, key: K) -> TraceContext {
        self.map.entry(key).or_default().clone()
    }

    pub fn remove(&self, key: &K) -> Option<TraceContext> {
        self.map.remove(key).map(|(_, v)| v)
    }
}

/// Stable encoding: length-prefixed fields, big-endian integers; [`BTreeMap`] iteration is key order.
///
/// The OpenTelemetry trace id prefix hashes into [`LogicFingerprint`] so evaluations with different
/// propagation contexts produce distinct fingerprints.
fn canonical_step_payload(otel_trace_id: Option<&str>, steps: &[TraceStep]) -> Vec<u8> {
    let mut out = Vec::new();
    write_len_prefixed_bytes(
        &mut out,
        otel_trace_id.unwrap_or("").as_bytes(),
    );

    for step in steps {
        out.extend_from_slice(&step.sequence.to_be_bytes());
        out.extend_from_slice(&step.captured_at_ms.to_be_bytes());
        write_len_prefixed_bytes(&mut out, step.rule_id.as_bytes());
        write_len_prefixed_bytes(&mut out, step.operator.as_bytes());

        let op_count: u32 = step
            .operands
            .len()
            .try_into()
            .expect("operand count fits u32 on supported targets");
        out.extend_from_slice(&op_count.to_be_bytes());
        for operand in &step.operands {
            write_len_prefixed_bytes(&mut out, operand.as_bytes());
        }

        out.push(u8::from(step.result));

        let scope_count: u32 = step
            .scope_snapshot
            .len()
            .try_into()
            .expect("scope size fits u32 on supported targets");
        out.extend_from_slice(&scope_count.to_be_bytes());
        for (key, value) in &step.scope_snapshot {
            write_len_prefixed_bytes(&mut out, key.as_bytes());
            write_len_prefixed_bytes(&mut out, value.as_bytes());
        }
    }

    out
}

fn write_len_prefixed_bytes(buf: &mut Vec<u8>, bytes: &[u8]) {
    let len_u32: u32 = bytes
        .len()
        .try_into()
        .expect("bounded field length fits u32");
    buf.extend_from_slice(&len_u32.to_be_bytes());
    buf.extend_from_slice(bytes);
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::{Arc, Barrier};
    use std::thread;

    #[test]
    fn empty_finalize_matches_sha256_empty() {
        let ctx = TraceContext::new();
        let fp = ctx.finalize().expect("finalize");
        // Logic fingerprint prefixes the canonical encoding with a length-prefixed OTEL trace id
        // (empty when unset), even when there are zero steps.
        let mut empty_canonical = Vec::new();
        empty_canonical.extend_from_slice(&0u32.to_be_bytes());
        let expected: [u8; 32] = Sha256::digest(&empty_canonical).into();
        assert_eq!(fp.sha256, expected);
        assert!(ctx.record_step("r", "AND", ["a"], true, &BTreeMap::new()).is_err());
    }

    #[test]
    fn fingerprint_non_empty_for_recorded_step() {
        let scope = BTreeMap::from([
            ("x".to_string().into_boxed_str(), "1".to_string().into_boxed_str()),
        ]);
        let ctx = TraceContext::new();
        ctx.record_step("r1", "AND", ["p", "q"], true, &scope)
            .unwrap();
        let fp = ctx.finalize().expect("finalize");

        let empty: [u8; 32] = Sha256::digest([]).into();
        assert_ne!(fp.sha256, empty);
    }

    #[test]
    fn concurrent_record_preserves_sequence_order_in_finalize() {
        const THREADS: usize = 8;
        const PER_THREAD: usize = 100;

        let ctx = TraceContext::new();
        let barrier = Arc::new(Barrier::new(THREADS + 1));

        let mut handles = Vec::new();
        for t in 0..THREADS {
            let ctx = ctx.clone();
            let barrier = barrier.clone();
            handles.push(thread::spawn(move || {
                barrier.wait();
                for i in 0..PER_THREAD {
                    let scope = BTreeMap::new();
                    let label = format!("t{t}_{i}");
                    ctx.record_step(&label, "OP", [label.as_str()], i % 2 == 0, &scope)
                        .expect("record");
                }
            }));
        }

        barrier.wait();
        for h in handles {
            h.join().expect("join");
        }

        let fp = ctx.finalize().expect("finalize");
        let expected: [u8; 32] = Sha256::digest([]).into();
        assert_ne!(fp.sha256, expected);
    }

    #[test]
    fn registry_isolates_contexts() {
        let reg = TraceContextRegistry::new();
        let a = reg.get_or_insert("eval-a".to_string());
        let b = reg.get_or_insert("eval-b".to_string());

        a.record_step("r", "X", std::iter::empty::<&str>(), false, &BTreeMap::new())
            .unwrap();
        b.record_step(
            "s",
            "Y",
            std::iter::empty::<&str>(),
            true,
            &BTreeMap::new(),
        )
        .unwrap();

        assert_ne!(
            a.finalize().expect("a").sha256,
            b.finalize().expect("b").sha256
        );
    }
}
