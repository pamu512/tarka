//! Recursive JSON rule [`Evaluator`] that feeds [`super::trace::TraceContext`] for evidence manifests.
//!
//! Production loads must use [`Evaluator::try_from_verified_rule_json`] so SHA-256(rule JSON bytes)
//! matches the requested content id (see [`super::rule_address`]).
//!
//! Composite nodes (`AND`, `OR`, `NOT`, `CUSTOM` routing) recurse without emitting trace rows; each
//! **leaf** comparison or external lookup records one [`TraceContext::record_step`] with the variable
//! snapshot **before** evaluation and the boolean outcome **after**.

use crate::engine::clock::{unix_nanos_for_clock, Clock, SharedClock};
use crate::engine::rule_address::{verify_rule_content_hex, RuleContentId, SecurityIntegrityViolation};
use crate::engine::trace::TraceContext;
use crate::metrics_export::{
    record_engine_latency_histogram_seconds, record_manifest_generation_error,
    record_tarka_engine_processing_time_seconds,
};
use crate::engine::wasm_sandbox::{
    evaluate_json_with_module, WasmModuleBytesRegistry, WasmRegistryError, WasmRuntimeState,
    WasmSandboxConfig,
};
use crate::evidence::{
    signal_value, CryptoSignature, EvidenceManifest, Header, InputMap, Metadata, SignalValue, Step,
    Trace,
};
use serde_json::Value;
use smallvec::{smallvec, SmallVec};
use std::collections::BTreeMap;
use std::time::SystemTime;
use thiserror::Error;
use tracing::Span;
use tracing_opentelemetry::OpenTelemetrySpanExt;
use uuid::Uuid;

/// Input payload type for evaluation (`serde_json::Value`).
pub type JsonValue = Value;

/// Decision plus manifest payload: `Ok` carries a full [`EvidenceManifest`]; fatal leaf failures yield [`PartialManifest`].
///
/// This matches the requested `(bool, EvidenceManifest)` shape on the success path while still returning auditable state when Redis/lists/custom hooks fail.
pub type EvaluateOutcome = (bool, Result<EvidenceManifest, PartialManifest>);

/// Stamp the active `tracing` span (when an OpenTelemetry layer is installed) with immutable
/// proof-oriented fields as OpenTelemetry string attributes (`tarka.*`), searchable in Jaeger,
/// Honeycomb, and other OTLP backends.
fn record_tarka_proof_otel_span_attributes(
    rule_content_id_hex: Option<&str>,
    final_decision: bool,
    manifest_logic_sha256_hex: Option<&str>,
) {
    let span = Span::current();
    if span.is_disabled() {
        return;
    }
    if let Some(raw) = rule_content_id_hex {
        let trimmed = raw.trim();
        if !trimmed.is_empty() {
            span.set_attribute("tarka.rule_id", trimmed.to_string());
        }
    }
    span.set_attribute(
        "tarka.decision",
        if final_decision { "true" } else { "false" }.to_string(),
    );
    if let Some(raw) = manifest_logic_sha256_hex {
        let trimmed = raw.trim();
        if !trimmed.is_empty() {
            span.set_attribute("tarka.manifest_hash", trimmed.to_string());
        }
    }
}

fn default_wasm_eval_export() -> String {
    "evaluate".to_string()
}

/// Comparison operators for leaf rules.
#[derive(Clone, Copy, Debug, Eq, PartialEq, serde::Deserialize, serde::Serialize)]
#[serde(rename_all = "snake_case")]
pub enum CompareOp {
    Eq,
    Ne,
    Lt,
    Lte,
    Gt,
    Gte,
    /// Substring containment after coercing operands to strings.
    StringContains,
}

/// Executable rule tree evaluated against JSON inputs.
///
/// JSON encoding uses `kind` as the discriminator (`and`, `or`, `compare_leaf`, …).
#[derive(Clone, Debug, serde::Deserialize, serde::Serialize)]
#[serde(tag = "kind", rename_all = "snake_case")]
pub enum RuleExpr {
    And {
        id: String,
        children: Vec<RuleExpr>,
    },
    Or {
        id: String,
        children: Vec<RuleExpr>,
    },
    Not {
        id: String,
        child: Box<RuleExpr>,
    },
    /// Compare a JSON pointer path against an expected [`Value`].
    CompareLeaf {
        id: String,
        path: String,
        op: CompareOp,
        expected: Value,
    },
    /// Compare `redis_get(key)` interpreted as UTF-8 text (JSON parsed when possible) against `expected`.
    RedisCompareLeaf {
        id: String,
        redis_key: String,
        op: CompareOp,
        expected: Value,
    },
    /// Membership check via [`ExternalDataSource::list_contains`].
    ListContainsLeaf {
        id: String,
        list_name: String,
        item_path: String,
    },
    /// Extension hook evaluated through [`ExternalDataSource::custom_eval`].
    CustomLeaf {
        id: String,
        name: String,
    },
    /// Sandboxed WebAssembly custom rule (zero-import module; see [`crate::engine::wasm_sandbox`]).
    WasmCustomLeaf {
        id: String,
        /// SHA-256 content id (hex) of the wasm artifact; must be registered on the [`Evaluator`] via [`Evaluator::with_wasm_modules`].
        wasm_content_id_hex: String,
        #[serde(default)]
        name: Option<String>,
        /// Guest export name implementing the rule ABI (defaults to `evaluate`).
        #[serde(default = "default_wasm_eval_export")]
        export: String,
    },
    /// Graph / LFFI proximity: true when ``context.graph_score`` (or top-level ``graph_score``) is **strictly greater than** ``threshold``.
    GraphMatch {
        id: String,
        threshold: f64,
    },
}

/// External integrations invoked from leaf rules (Redis, curated lists, bespoke logic).
pub trait ExternalDataSource {
    fn redis_get(&self, key: &str) -> Result<String, ExternalError>;

    fn list_contains(&self, list: &str, item: &str) -> Result<bool, ExternalError>;

    fn custom_eval(&self, name: &str, data: &Value) -> Result<bool, ExternalError>;
}

/// Structured failure from an [`ExternalDataSource`] implementation.
#[derive(Debug, Error)]
pub enum ExternalError {
    #[error("redis key `{key}`: {message}")]
    Redis { key: String, message: String },
    #[error("list `{list}`: {message}")]
    List { list: String, message: String },
    #[error("custom `{name}`: {message}")]
    Custom { name: String, message: String },
}

/// Reason a specific leaf rule aborted evaluation (surfaced through [`EvalFatalError::Rule`]).
#[derive(Debug, Error)]
pub enum RuleFail {
    #[error(transparent)]
    External(#[from] ExternalError),
    #[error(transparent)]
    Json(#[from] serde_json::Error),
    #[error("{0}")]
    Comparison(String),
    #[error("wasm sandbox: {0}")]
    Wasm(String),
    #[error("trace recorder closed unexpectedly")]
    TracePoisoned,
}

/// Fatal evaluation errors that yield a [`PartialManifest`] instead of panicking.
#[derive(Debug, Error)]
pub enum EvalFatalError {
    #[error("rule `{rule_id}`: {source}")]
    Rule {
        rule_id: String,
        #[source]
        source: RuleFail,
    },
}

impl EvalFatalError {
    fn rule(rule_id: impl Into<String>, source: RuleFail) -> Self {
        EvalFatalError::Rule {
            rule_id: rule_id.into(),
            source,
        }
    }
}

/// Evidence bundle plus structured failure metadata when evaluation aborts before a clean manifest.
#[derive(Clone, Debug)]
pub struct PartialManifest {
    pub evidence: EvidenceManifest,
    pub failure_message: String,
    pub failing_rule_id: Option<String>,
}

/// Parses JSON rule bytes only after verifying [`crate::engine::rule_address::rule_content_sha256`]
/// equals the digest encoded by `requested_content_id_hex`.
pub fn parse_verified_rule_json(
    raw_rule_json_bytes: &[u8],
    requested_content_id_hex: &str,
) -> Result<RuleExpr, SecurityIntegrityViolation> {
    verify_rule_content_hex(raw_rule_json_bytes, requested_content_id_hex)?;
    serde_json::from_slice(raw_rule_json_bytes).map_err(Into::into)
}

/// Rule evaluator configured with a [`RuleExpr`] tree, [`TraceContext`], and [`ExternalDataSource`].
pub struct Evaluator<D: ExternalDataSource> {
    pub root: RuleExpr,
    pub trace: TraceContext,
    external: D,
    pub engine_version: String,
    wasm: Option<WasmRuntimeState>,
    eval_clock: SharedClock,
    /// Verified rule content id (SHA-256 hex of rule JSON), when built via [`Self::try_from_verified_rule_json`].
    rule_content_id_hex: Option<String>,
}

impl<D: ExternalDataSource> Evaluator<D> {
    pub fn new(
        root: RuleExpr,
        trace: TraceContext,
        external: D,
        engine_version: impl Into<String>,
    ) -> Self {
        let eval_clock = trace.clock();
        Self {
            root,
            trace,
            external,
            engine_version: engine_version.into(),
            wasm: None,
            eval_clock,
            rule_content_id_hex: None,
        }
    }

    /// Wall-clock source for this evaluation (production [`crate::engine::clock::SystemClock`] or replay [`crate::engine::clock::FixedClock`]).
    #[inline]
    pub fn clock(&self) -> SharedClock {
        self.eval_clock.clone()
    }

    /// Convenience: [`Clock::now`] for time-dependent rule extensions.
    #[inline]
    pub fn wall_now(&self) -> SystemTime {
        self.eval_clock.now()
    }

    fn reset_trace_preserving_otel(&mut self) {
        self.trace = TraceContext::with_clock_and_otel(
            self.eval_clock.clone(),
            self.trace.otel_trace_id_cloned(),
        );
    }

    /// Attaches content-addressed wasm modules (SHA-256 hex key → bytes). Each key must match
    /// [`crate::engine::rule_address::rule_content_sha256`] of its bytes. Modules are preflighted
    /// (no imports, bounded memory) and compiled up front.
    pub fn with_wasm_modules(
        mut self,
        registry: WasmModuleBytesRegistry,
        config: WasmSandboxConfig,
    ) -> Result<Self, WasmRegistryError> {
        self.wasm = if registry.is_empty() {
            None
        } else {
            Some(WasmRuntimeState::from_verified_registry(registry, config)?)
        };
        Ok(self)
    }

    /// Builds an evaluator after verifying `sha256(raw_rule_json_bytes)` matches `requested_content_id_hex`.
    /// The engine refuses to start when verification fails ([`SecurityIntegrityViolation`]).
    pub fn try_from_verified_rule_json(
        raw_rule_json_bytes: &[u8],
        requested_content_id_hex: &str,
        trace: TraceContext,
        external: D,
        engine_version: impl Into<String>,
    ) -> Result<Self, SecurityIntegrityViolation> {
        let root = parse_verified_rule_json(raw_rule_json_bytes, requested_content_id_hex)?;
        let mut ev = Self::new(root, trace, external, engine_version);
        ev.rule_content_id_hex = Some(requested_content_id_hex.to_ascii_lowercase());
        Ok(ev)
    }

    /// Evaluates `data`, emitting leaf-node [`TraceContext::record_step`] rows and returning the
    /// boolean decision plus either a complete [`EvidenceManifest`] or a [`PartialManifest`] when an
    /// external error occurs.
    ///
    /// The trace buffer is finalized (`logic_fingerprint` via SHA-256 happens inside
    /// [`TraceContext::finalize_with_trace`]); after this call returns, [`Self::trace`] is replaced
    /// with a fresh [`TraceContext`] so the evaluator can be reused.
    pub fn evaluate(&mut self, data: &Value) -> EvaluateOutcome {
        let wall_start = self.eval_clock.now();
        let root = self.root.clone();
        let outcome = self.eval_expr(&root, data);
        let elapsed_us = self
            .eval_clock
            .now()
            .duration_since(wall_start)
            .map(|d| d.as_micros() as u64)
            .unwrap_or(0);

        let elapsed_s = elapsed_us as f64 / 1_000_000.0;
        record_engine_latency_histogram_seconds(elapsed_s);

        let tuple = match outcome {
            Ok(decision) => match self.trace.finalize_with_trace() {
                Ok((fp, steps)) => {
                    let fp_hex = hex::encode(fp.sha256);
                    record_tarka_proof_otel_span_attributes(
                        self.rule_content_id_hex.as_deref(),
                        decision,
                        Some(fp_hex.as_str()),
                    );
                    let otel = self.trace.otel_trace_id();
                    let manifest = build_evidence_manifest(
                        &steps,
                        data,
                        &self.engine_version,
                        decision,
                        elapsed_us,
                        self.eval_clock.as_ref(),
                        otel,
                    );
                    self.reset_trace_preserving_otel();
                    (decision, Ok(manifest))
                }
                Err(e) => {
                    record_tarka_proof_otel_span_attributes(
                        self.rule_content_id_hex.as_deref(),
                        decision,
                        None,
                    );
                    self.reset_trace_preserving_otel();
                    (
                        false,
                        Err(PartialManifest {
                            evidence: empty_manifest(),
                            failure_message: format!("trace finalize: {e}"),
                            failing_rule_id: None,
                        }),
                    )
                }
            },
            Err(fatal) => {
                let partial = match self.trace.finalize_with_trace() {
                    Ok((fp, steps)) => {
                        let fp_hex = hex::encode(fp.sha256);
                        record_tarka_proof_otel_span_attributes(
                            self.rule_content_id_hex.as_deref(),
                            false,
                            Some(fp_hex.as_str()),
                        );
                        let otel = self.trace.otel_trace_id();
                        build_partial_manifest(
                            fatal,
                            &steps,
                            data,
                            &self.engine_version,
                            elapsed_us,
                            self.eval_clock.as_ref(),
                            otel,
                        )
                    }
                    Err(e) => {
                        record_tarka_proof_otel_span_attributes(
                            self.rule_content_id_hex.as_deref(),
                            false,
                            None,
                        );
                        PartialManifest {
                            evidence: empty_manifest(),
                            failure_message: format!("trace finalize after error ({e}): {fatal}"),
                            failing_rule_id: None,
                        }
                    }
                };
                self.reset_trace_preserving_otel();
                (false, Err(partial))
            }
        };

        let processing_us = self
            .eval_clock
            .now()
            .duration_since(wall_start)
            .map(|d| d.as_micros() as u64)
            .unwrap_or(0);
        let processing_s = processing_us as f64 / 1_000_000.0;
        record_tarka_engine_processing_time_seconds(processing_s);

        if tuple.1.is_err() {
            record_manifest_generation_error();
        }

        tuple
    }

    fn eval_expr(&self, expr: &RuleExpr, data: &Value) -> Result<bool, EvalFatalError> {
        match expr {
            RuleExpr::And { children, .. } => {
                let mut acc = true;
                for child in children {
                    acc = acc && self.eval_expr(child, data)?;
                    if !acc {
                        break;
                    }
                }
                Ok(acc)
            }
            RuleExpr::Or { children, .. } => {
                let mut any = false;
                for child in children {
                    let r = self.eval_expr(child, data)?;
                    if r {
                        any = true;
                        break;
                    }
                }
                Ok(any)
            }
            RuleExpr::Not { child, .. } => Ok(!self.eval_expr(child, data)?),
            RuleExpr::CompareLeaf {
                id,
                path,
                op,
                expected,
            } => self.eval_compare_leaf(id, path, *op, expected, data),
            RuleExpr::RedisCompareLeaf {
                id,
                redis_key,
                op,
                expected,
            } => self.eval_redis_compare_leaf(id, redis_key, *op, expected, data),
            RuleExpr::ListContainsLeaf {
                id,
                list_name,
                item_path,
            } => self.eval_list_contains_leaf(id, list_name, item_path, data),
            RuleExpr::CustomLeaf { id, name } => self.eval_custom_leaf(id, name, data),
            RuleExpr::WasmCustomLeaf {
                id,
                wasm_content_id_hex,
                name,
                export,
            } => self.eval_wasm_custom_leaf(id, wasm_content_id_hex, export, name.as_deref(), data),
            RuleExpr::GraphMatch { id, threshold } => self.eval_graph_match(id, *threshold, data),
        }
    }

    fn eval_graph_match(
        &self,
        rule_id: &str,
        threshold: f64,
        data: &Value,
    ) -> Result<bool, EvalFatalError> {
        let score_opt = graph_score_from_payload(data);
        let score_str = match score_opt {
            Some(s) => s.to_string(),
            None => "null".to_string(),
        };

        let mut scope: BTreeMap<Box<str>, Box<str>> = BTreeMap::new();
        scope.insert("context.graph_score".into(), score_str.into_boxed_str());
        scope.insert(
            "graph_match.threshold".into(),
            format!("{threshold}").into_boxed_str(),
        );

        let pass = match score_opt {
            Some(score) if score.is_finite() => score > threshold,
            _ => false,
        };
        scope.insert(
            "graph_match.result".into(),
            pass.to_string().into_boxed_str(),
        );

        let operands: SmallVec<[Box<str>; 8]> = smallvec![
            format!("threshold={threshold}").into_boxed_str(),
        ];

        self.trace
            .record_step(
                rule_id,
                "GRAPH_MATCH",
                operands.iter().map(|s| s.as_ref()),
                pass,
                &scope,
            )
            .map_err(|_| EvalFatalError::rule(rule_id, RuleFail::TracePoisoned))?;

        Ok(pass)
    }

    fn eval_compare_leaf(
        &self,
        rule_id: &str,
        path: &str,
        op: CompareOp,
        expected: &Value,
        data: &Value,
    ) -> Result<bool, EvalFatalError> {
        let pointer = normalize_json_pointer(path);
        let actual = data.pointer(&pointer).cloned().unwrap_or(Value::Null);
        let input_before = serde_json::to_string(&actual).map_err(|e| {
            EvalFatalError::rule(rule_id, RuleFail::Json(e))
        })?;
        let expected_json = serde_json::to_string(expected).map_err(|e| {
            EvalFatalError::rule(rule_id, RuleFail::Json(e))
        })?;

        let mut scope: BTreeMap<Box<str>, Box<str>> = BTreeMap::new();
        scope.insert(
            "input.before".into(),
            input_before.clone().into_boxed_str(),
        );
        scope.insert("expected.json".into(), expected_json.into_boxed_str());
        scope.insert("comparison.op".into(), format!("{op:?}").into_boxed_str());

        let pass = compare_json_values(&actual, op, expected).map_err(|msg| {
            EvalFatalError::rule(rule_id, RuleFail::Comparison(msg))
        })?;

        scope.insert("comparison.result".into(), pass.to_string().into_boxed_str());
        scope.insert(
            "input.after".into(),
            serde_json::to_string(&actual)
                .map_err(|e| EvalFatalError::rule(rule_id, RuleFail::Json(e)))?
                .into_boxed_str(),
        );

        let operands: SmallVec<[Box<str>; 8]> = smallvec![
            pointer.into_boxed_str(),
            format!("op={op:?}").into_boxed_str(),
        ];

        self.trace
            .record_step(
                rule_id,
                "COMPARE",
                operands.iter().map(|s| s.as_ref()),
                pass,
                &scope,
            )
            .map_err(|_| EvalFatalError::rule(rule_id, RuleFail::TracePoisoned))?;

        Ok(pass)
    }

    fn eval_redis_compare_leaf(
        &self,
        rule_id: &str,
        redis_key: &str,
        op: CompareOp,
        expected: &Value,
        _data: &Value,
    ) -> Result<bool, EvalFatalError> {
        let retrieved = self.external.redis_get(redis_key).map_err(|e| {
            EvalFatalError::rule(rule_id, RuleFail::External(e))
        })?;

        let mut scope: BTreeMap<Box<str>, Box<str>> = BTreeMap::new();
        scope.insert("redis.key".into(), redis_key.to_string().into_boxed_str());
        scope.insert(
            "redis.value.raw".into(),
            retrieved.clone().into_boxed_str(),
        );

        let parsed_actual: Value = serde_json::from_str(&retrieved).unwrap_or(Value::String(retrieved));
        let input_before = serde_json::to_string(&parsed_actual).map_err(|e| {
            EvalFatalError::rule(rule_id, RuleFail::Json(e))
        })?;
        scope.insert("external.actual.json".into(), input_before.into_boxed_str());

        let expected_json = serde_json::to_string(expected).map_err(|e| {
            EvalFatalError::rule(rule_id, RuleFail::Json(e))
        })?;
        scope.insert("expected.json".into(), expected_json.into_boxed_str());

        let pass = compare_json_values(&parsed_actual, op, expected).map_err(|msg| {
            EvalFatalError::rule(rule_id, RuleFail::Comparison(msg))
        })?;
        scope.insert("comparison.result".into(), pass.to_string().into_boxed_str());

        let operands: SmallVec<[Box<str>; 8]> = smallvec![
            redis_key.to_string().into_boxed_str(),
            format!("op={op:?}").into_boxed_str(),
        ];

        self.trace
            .record_step(rule_id, "REDIS", operands.iter().map(|s| s.as_ref()), pass, &scope)
            .map_err(|_| EvalFatalError::rule(rule_id, RuleFail::TracePoisoned))?;

        Ok(pass)
    }

    fn eval_list_contains_leaf(
        &self,
        rule_id: &str,
        list_name: &str,
        item_path: &str,
        data: &Value,
    ) -> Result<bool, EvalFatalError> {
        let pointer = normalize_json_pointer(item_path);
        let item_value = data.pointer(&pointer).cloned().unwrap_or(Value::Null);
        let item_str = json_scalar_to_string(&item_value).map_err(|e| {
            EvalFatalError::rule(rule_id, e)
        })?;

        let contains = self.external.list_contains(list_name, &item_str).map_err(|e| {
            EvalFatalError::rule(rule_id, RuleFail::External(e))
        })?;

        let mut scope: BTreeMap<Box<str>, Box<str>> = BTreeMap::new();
        scope.insert("list.name".into(), list_name.to_string().into_boxed_str());
        scope.insert(
            "list.item.path".into(),
            pointer.clone().into_boxed_str(),
        );
        scope.insert(
            "list.item.resolved".into(),
            item_str.clone().into_boxed_str(),
        );
        scope.insert(
            "list.lookup.contains".into(),
            contains.to_string().into_boxed_str(),
        );

        let operands: SmallVec<[Box<str>; 8]> = smallvec![
            list_name.to_string().into_boxed_str(),
            pointer.into_boxed_str(),
        ];

        self.trace
            .record_step(
                rule_id,
                "LIST",
                operands.iter().map(|s| s.as_ref()),
                contains,
                &scope,
            )
            .map_err(|_| EvalFatalError::rule(rule_id, RuleFail::TracePoisoned))?;

        Ok(contains)
    }

    fn eval_custom_leaf(
        &self,
        rule_id: &str,
        name: &str,
        data: &Value,
    ) -> Result<bool, EvalFatalError> {
        let outcome = self.external.custom_eval(name, data).map_err(|e| {
            EvalFatalError::rule(rule_id, RuleFail::External(e))
        })?;

        let mut scope: BTreeMap<Box<str>, Box<str>> = BTreeMap::new();
        scope.insert("custom.name".into(), name.to_string().into_boxed_str());
        scope.insert(
            "custom.result".into(),
            outcome.to_string().into_boxed_str(),
        );

        let operands: SmallVec<[Box<str>; 8]> = smallvec![name.to_string().into_boxed_str()];

        self.trace
            .record_step(
                rule_id,
                "CUSTOM",
                operands.iter().map(|s| s.as_ref()),
                outcome,
                &scope,
            )
            .map_err(|_| EvalFatalError::rule(rule_id, RuleFail::TracePoisoned))?;

        Ok(outcome)
    }

    fn eval_wasm_custom_leaf(
        &self,
        rule_id: &str,
        wasm_content_id_hex: &str,
        export_name: &str,
        label_name: Option<&str>,
        data: &Value,
    ) -> Result<bool, EvalFatalError> {
        let resolved_id = RuleContentId::parse_hex(wasm_content_id_hex).map_err(|e| {
            EvalFatalError::rule(
                rule_id,
                RuleFail::Wasm(format!("invalid wasm content id: {e}")),
            )
        })?;
        let hex_key = resolved_id.to_hex();

        let runtime = self.wasm.as_ref().ok_or_else(|| {
            EvalFatalError::rule(
                rule_id,
                RuleFail::Wasm(
                    "no wasm modules registered; call Evaluator::with_wasm_modules before evaluating wasm_custom_leaf rules".into(),
                ),
            )
        })?;

        let module = runtime.modules.get(&hex_key).ok_or_else(|| {
            EvalFatalError::rule(
                rule_id,
                RuleFail::Wasm(format!(
                    "wasm module `{hex_key}` not loaded in evaluator registry"
                )),
            )
        })?;

        let pass = evaluate_json_with_module(
            &runtime.engine,
            module.as_ref(),
            &runtime.config,
            export_name,
            data,
        )
        .map_err(|e| EvalFatalError::rule(rule_id, RuleFail::Wasm(e.to_string())))?;

        let mut scope: BTreeMap<Box<str>, Box<str>> = BTreeMap::new();
        scope.insert(
            "wasm.content_id_hex".into(),
            hex_key.clone().into_boxed_str(),
        );
        scope.insert(
            "wasm.export".into(),
            export_name.to_string().into_boxed_str(),
        );
        if let Some(n) = label_name {
            scope.insert("wasm.label".into(), n.to_string().into_boxed_str());
        }
        scope.insert(
            "wasm.result".into(),
            pass.to_string().into_boxed_str(),
        );

        let operands: SmallVec<[Box<str>; 8]> = smallvec![
            hex_key.into_boxed_str(),
            export_name.to_string().into_boxed_str(),
        ];

        self.trace
            .record_step(
                rule_id,
                "WASM",
                operands.iter().map(|s| s.as_ref()),
                pass,
                &scope,
            )
            .map_err(|_| EvalFatalError::rule(rule_id, RuleFail::TracePoisoned))?;

        Ok(pass)
    }
}

/// Resolve ``context.graph_score`` then top-level ``graph_score`` for [`RuleExpr::GraphMatch`].
fn graph_score_from_payload(data: &Value) -> Option<f64> {
    let v = data
        .pointer("/context/graph_score")
        .or_else(|| data.pointer("/graph_score"))?;
    match v {
        Value::Number(n) => n.as_f64(),
        Value::String(s) => s.parse().ok(),
        Value::Bool(b) => Some(if *b { 1.0 } else { 0.0 }),
        _ => None,
    }
}

fn normalize_json_pointer(path: &str) -> String {
    if path.is_empty() || path.starts_with('/') {
        path.to_string()
    } else {
        format!("/{}", path.trim_start_matches('/'))
    }
}

fn json_scalar_to_string(value: &Value) -> Result<String, RuleFail> {
    match value {
        Value::String(s) => Ok(s.clone()),
        Value::Null => Ok(String::new()),
        Value::Bool(b) => Ok(b.to_string()),
        Value::Number(n) => Ok(n.to_string()),
        Value::Array(_) | Value::Object(_) => Err(RuleFail::Comparison(
            "list membership expects scalar JSON value".into(),
        )),
    }
}

fn compare_json_values(
    actual: &Value,
    op: CompareOp,
    expected: &Value,
) -> Result<bool, String> {
    match op {
        CompareOp::Eq => Ok(actual == expected),
        CompareOp::Ne => Ok(actual != expected),
        CompareOp::StringContains => {
            let left = stringify_for_compare(actual);
            let right = stringify_for_compare(expected);
            Ok(left.contains(&right))
        }
        CompareOp::Lt | CompareOp::Lte | CompareOp::Gt | CompareOp::Gte => {
            compare_ordered_numbers(actual, op, expected)
        }
    }
}

fn stringify_for_compare(value: &Value) -> String {
    match value {
        Value::String(s) => s.clone(),
        other => other.to_string(),
    }
}

fn compare_ordered_numbers(
    actual: &Value,
    op: CompareOp,
    expected: &Value,
) -> Result<bool, String> {
    let av = number_rank(actual)?;
    let ev = number_rank(expected)?;
    let cmp = av.partial_cmp(&ev).ok_or_else(|| {
        format!("non-comparable numeric ordering: {actual} vs {expected}")
    })?;
    let ok = match op {
        CompareOp::Lt => cmp == std::cmp::Ordering::Less,
        CompareOp::Lte => matches!(
            cmp,
            std::cmp::Ordering::Less | std::cmp::Ordering::Equal
        ),
        CompareOp::Gt => cmp == std::cmp::Ordering::Greater,
        CompareOp::Gte => matches!(
            cmp,
            std::cmp::Ordering::Greater | std::cmp::Ordering::Equal
        ),
        _ => unreachable!("caller filters ops"),
    };
    Ok(ok)
}

fn number_rank(value: &Value) -> Result<f64, String> {
    match value {
        Value::Number(n) => n
            .as_f64()
            .ok_or_else(|| format!("unsupported number {n}")),
        Value::String(s) => s
            .parse::<f64>()
            .map_err(|_| format!("cannot parse `{s}` as number")),
        other => Err(format!("expected numeric operand, got {other}")),
    }
}

fn empty_manifest() -> EvidenceManifest {
    EvidenceManifest {
        header: None,
        input_map: None,
        trace: None,
        metadata: None,
        crypto_signature: None,
    }
}

fn build_evidence_manifest(
    trace_steps: &[crate::engine::trace::TraceStep],
    data: &Value,
    engine_version: &str,
    decision: bool,
    elapsed_us: u64,
    clock: &dyn Clock,
    otel_trace_id: Option<&str>,
) -> EvidenceManifest {
    let steps: Vec<Step> = trace_steps
        .iter()
        .map(|s| trace_step_to_proto(s, otel_trace_id))
        .collect();
    EvidenceManifest {
        header: Some(build_header(engine_version, clock)),
        input_map: Some(input_map_from_json(data)),
        trace: Some(Trace { steps }),
        metadata: Some(Metadata {
            final_decision: decision,
            total_execution_time_us: elapsed_us,
        }),
        crypto_signature: Some(CryptoSignature {
            algorithm: "none".into(),
            signature: Vec::new(),
            key_id: String::new(),
        }),
    }
}

fn build_partial_manifest(
    err: EvalFatalError,
    trace_steps: &[crate::engine::trace::TraceStep],
    data: &Value,
    engine_version: &str,
    elapsed_us: u64,
    clock: &dyn Clock,
    otel_trace_id: Option<&str>,
) -> PartialManifest {
    let failing_rule_id = failing_rule_id_from_fatal(&err).or_else(|| {
        trace_steps
            .last()
            .map(|s| s.rule_id.to_string())
    });

    let evidence = EvidenceManifest {
        header: Some(build_header(engine_version, clock)),
        input_map: Some(input_map_from_json(data)),
        trace: Some(Trace {
            steps: trace_steps
                .iter()
                .map(|s| trace_step_to_proto(s, otel_trace_id))
                .collect(),
        }),
        metadata: Some(Metadata {
            final_decision: false,
            total_execution_time_us: elapsed_us,
        }),
        crypto_signature: Some(CryptoSignature {
            algorithm: "none".into(),
            signature: Vec::new(),
            key_id: String::new(),
        }),
    };

    PartialManifest {
        evidence,
        failure_message: err.to_string(),
        failing_rule_id,
    }
}

fn failing_rule_id_from_fatal(err: &EvalFatalError) -> Option<String> {
    match err {
        EvalFatalError::Rule { rule_id, .. } => Some(rule_id.clone()),
    }
}

fn build_header(engine_version: &str, clock: &dyn Clock) -> Header {
    Header {
        manifest_id: Uuid::now_v7().as_bytes().to_vec(),
        engine_version: engine_version.to_string(),
        timestamp_ns: unix_nanos_for_clock(clock),
        engine_fingerprint: super::node_identity::engine_fingerprint().to_string(),
    }
}

fn trace_step_to_proto(
    s: &crate::engine::trace::TraceStep,
    otel_trace_id: Option<&str>,
) -> Step {
    Step {
        rule_id: s.rule_id.to_string(),
        logic_operator: s.operator.to_string(),
        operands: s.operands.iter().map(|o| o.to_string()).collect(),
        result: s.result,
        state_snapshot: s
            .scope_snapshot
            .iter()
            .map(|(k, v)| (k.to_string(), v.to_string()))
            .collect(),
        otel_trace_id: otel_trace_id.unwrap_or("").to_string(),
    }
}

fn input_map_from_json(root: &Value) -> InputMap {
    let mut entries = BTreeMap::new();
    flatten_json("", root, &mut entries);
    InputMap { entries }
}

fn flatten_json(prefix: &str, value: &Value, out: &mut BTreeMap<String, SignalValue>) {
    match value {
        Value::Object(map) => {
            if map.is_empty() && prefix.is_empty() {
                out.insert(
                    "_empty_object".to_string(),
                    json_to_signal_value(&Value::Object(map.clone())),
                );
                return;
            }
            for (key, child) in map {
                let next = if prefix.is_empty() {
                    key.clone()
                } else {
                    format!("{prefix}.{key}")
                };
                flatten_json(&next, child, out);
            }
        }
        Value::Array(items) => {
            for (idx, child) in items.iter().enumerate() {
                let next = if prefix.is_empty() {
                    format!("[{idx}]")
                } else {
                    format!("{prefix}[{idx}]")
                };
                flatten_json(&next, child, out);
            }
        }
        _ => {
            let key = if prefix.is_empty() {
                "_root".to_string()
            } else {
                prefix.to_string()
            };
            out.insert(key, json_to_signal_value(value));
        }
    }
}

fn json_to_signal_value(value: &Value) -> SignalValue {
    match value {
        Value::Null => SignalValue {
            value: Some(signal_value::Value::StringValue(String::new())),
        },
        Value::Bool(b) => SignalValue {
            value: Some(signal_value::Value::BoolValue(*b)),
        },
        Value::Number(n) => {
            if let Some(i) = n.as_i64() {
                SignalValue {
                    value: Some(signal_value::Value::IntValue(i)),
                }
            } else if let Some(u) = n.as_u64() {
                SignalValue {
                    value: Some(signal_value::Value::IntValue(u as i64)),
                }
            } else if let Some(f) = n.as_f64() {
                SignalValue {
                    value: Some(signal_value::Value::DoubleValue(f)),
                }
            } else {
                SignalValue {
                    value: Some(signal_value::Value::StringValue(n.to_string())),
                }
            }
        }
        Value::String(s) => SignalValue {
            value: Some(signal_value::Value::StringValue(s.clone())),
        },
        Value::Array(_) | Value::Object(_) => SignalValue {
            value: Some(signal_value::Value::StringValue(value.to_string())),
        },
    }
}

/// Hash-map backed stub for tests and local tooling.
#[derive(Clone, Default)]
pub struct MockExternal {
    pub redis: std::collections::HashMap<String, String>,
    pub lists: std::collections::HashMap<String, Vec<String>>,
    pub customs: std::collections::HashMap<String, bool>,
}

impl ExternalDataSource for MockExternal {
    fn redis_get(&self, key: &str) -> Result<String, ExternalError> {
        self.redis.get(key).cloned().ok_or_else(|| ExternalError::Redis {
            key: key.to_string(),
            message: "missing key".into(),
        })
    }

    fn list_contains(&self, list: &str, item: &str) -> Result<bool, ExternalError> {
        let items = self.lists.get(list).ok_or_else(|| ExternalError::List {
            list: list.to_string(),
            message: "unknown list".into(),
        })?;
        Ok(items.iter().any(|entry| entry == item))
    }

    fn custom_eval(&self, name: &str, _data: &Value) -> Result<bool, ExternalError> {
        self.customs.get(name).copied().ok_or_else(|| ExternalError::Custom {
            name: name.to_string(),
            message: "unknown custom rule".into(),
        })
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::engine::rule_address::rule_content_sha256;
    use crate::engine::trace::TraceContext;
    use crate::engine::wasm_sandbox::{WasmSandboxConfig, WasmSandboxError};
    use serde_json::json;
    use std::collections::HashMap;
    use std::sync::Arc;

    fn wasm_bytes_from_wat(wat: &str) -> Arc<[u8]> {
        wat::parse_str(wat).expect("wat").into()
    }

    #[test]
    fn wasm_custom_leaf_evaluates_true() {
        let wasm = wasm_bytes_from_wat(
            r#"(module
              (memory 1)
              (export "memory" (memory 0))
              (func (export "evaluate") (param i32 i32) (result i32)
                i32.const 1))"#,
        );
        let hex_id = hex::encode(rule_content_sha256(wasm.as_ref()));
        let mut reg = HashMap::new();
        reg.insert(hex_id.clone(), wasm);

        let rule = RuleExpr::WasmCustomLeaf {
            id: "w".into(),
            wasm_content_id_hex: hex_id.clone(),
            name: Some("always-true".into()),
            export: "evaluate".into(),
        };

        let mut eval = Evaluator::new(rule, TraceContext::new(), MockExternal::default(), "test")
            .with_wasm_modules(reg, WasmSandboxConfig::default())
            .expect("registry");

        let data = json!({"x": 1});
        let (decision, manifest) = eval.evaluate(&data);
        assert!(decision);
        let step = &manifest.expect("manifest").trace.expect("trace").steps[0];
        assert_eq!(step.logic_operator, "WASM");
        assert_eq!(step.result, true);
    }

    #[test]
    fn wasm_custom_leaf_out_of_fuel_returns_partial_manifest() {
        let wasm = wasm_bytes_from_wat(
            r#"(module
              (memory 1)
              (export "memory" (memory 0))
              (func (export "evaluate") (param i32 i32) (result i32)
                (loop (br 0))
                i32.const 1))"#,
        );
        let hex_id = hex::encode(rule_content_sha256(wasm.as_ref()));
        let mut reg = HashMap::new();
        reg.insert(hex_id.clone(), wasm);

        let rule = RuleExpr::WasmCustomLeaf {
            id: "fuel".into(),
            wasm_content_id_hex: hex_id,
            name: None,
            export: "evaluate".into(),
        };

        let tight = WasmSandboxConfig {
            max_linear_memory_bytes: crate::engine::wasm_sandbox::MAX_CUSTOM_RULE_WASM_MEMORY_BYTES,
            fuel_units: 2_000,
        };

        let mut eval = Evaluator::new(rule, TraceContext::new(), MockExternal::default(), "test")
            .with_wasm_modules(reg, tight)
            .expect("registry");

        let (decision, outcome) = eval.evaluate(&json!({}));
        assert!(!decision);
        let partial = outcome.expect_err("partial");
        assert!(
            partial.failure_message.contains("OutOfFuel")
                || partial.failure_message.contains("fuel"),
            "{}",
            partial.failure_message
        );
    }

    #[test]
    fn wasm_registry_rejects_digest_mismatch() {
        let wasm = wasm_bytes_from_wat(
            r#"(module
              (memory 1)
              (export "memory" (memory 0))
              (func (export "evaluate") (param i32 i32) (result i32)
                i32.const 0))"#,
        );
        let wrong_key = "ab".repeat(32);
        let mut reg = HashMap::new();
        reg.insert(wrong_key, wasm);

        match Evaluator::new(
            RuleExpr::CompareLeaf {
                id: "noop".into(),
                path: "/a".into(),
                op: CompareOp::Eq,
                expected: json!(1),
            },
            TraceContext::new(),
            MockExternal::default(),
            "test",
        )
        .with_wasm_modules(reg, WasmSandboxConfig::default())
        {
            Ok(_) => panic!("digest mismatch expected"),
            Err(e) => assert!(matches!(
                e,
                crate::engine::wasm_sandbox::WasmRegistryError::DigestMismatch { .. }
            )),
        }
    }

    #[test]
    fn wasm_preflight_rejects_imports() {
        let wasm = wasm_bytes_from_wat(
            r#"(module
              (import "host" "evil" (func))
              (memory 1)
              (export "memory" (memory 0))
              (func (export "evaluate") (param i32 i32) (result i32)
                i32.const 0))"#,
        );
        let err =
            crate::engine::wasm_sandbox::validate_wasm_bytes_for_custom_rule(wasm.as_ref(), 1024)
                .expect_err("imports forbidden");
        assert!(matches!(
            err,
            WasmSandboxError::ForbiddenImports { count } if count > 0
        ));
    }

    #[test]
    fn replay_mode_manifest_header_matches_injected_clock() {
        use std::sync::Arc;

        use crate::engine::clock::{unix_nanos_for_clock, FixedClock};

        let ns = 1_700_000_000_123_456_789_u128;
        let clock = Arc::new(FixedClock::from_unix_nanos(ns));
        let trace = TraceContext::with_clock_and_otel(clock.clone(), None);
        let rule = RuleExpr::CompareLeaf {
            id: "leaf.x".into(),
            path: "/x".into(),
            op: CompareOp::Eq,
            expected: json!(1),
        };
        let mut eval = Evaluator::new(rule, trace, MockExternal::default(), "test");
        let (_decision, manifest) = eval.evaluate(&json!({"x": 1}));
        let header = manifest.expect("manifest").header.expect("header");
        assert_eq!(
            header.timestamp_ns,
            unix_nanos_for_clock(clock.as_ref())
        );
    }

    #[test]
    fn evidence_steps_carry_otel_trace_id() {
        let tid = "a".repeat(32);
        let trace = TraceContext::with_otel_trace_id(Some(tid.clone()));
        let rule = RuleExpr::CompareLeaf {
            id: "leaf.x".into(),
            path: "/x".into(),
            op: CompareOp::Eq,
            expected: json!(1),
        };
        let mut eval = Evaluator::new(rule, trace, MockExternal::default(), "test");
        let (_decision, manifest) = eval.evaluate(&json!({"x": 1}));
        let m = manifest.expect("manifest");
        let step = &m.trace.expect("trace").steps[0];
        assert_eq!(step.otel_trace_id, tid);
    }

    #[test]
    fn compare_and_short_circuit_records_only_evaluated_leaves() {
        let json = serde_json::json!({"a": 1, "b": 2});
        let rule = RuleExpr::And {
            id: "root.and".into(),
            children: vec![
                RuleExpr::CompareLeaf {
                    id: "leaf.b.fail".into(),
                    path: "/b".into(),
                    op: CompareOp::Eq,
                    expected: json!(99),
                },
                RuleExpr::CompareLeaf {
                    id: "leaf.never".into(),
                    path: "/a".into(),
                    op: CompareOp::Eq,
                    expected: json!(1),
                },
            ],
        };

        let mut eval = Evaluator::new(rule, TraceContext::new(), MockExternal::default(), "test");
        let (decision, manifest) = eval.evaluate(&json);
        assert!(!decision);
        let m = manifest.expect("manifest");
        let trace = m.trace.expect("trace");
        assert_eq!(trace.steps.len(), 1);
        assert_eq!(trace.steps[0].rule_id, "leaf.b.fail");
    }

    #[test]
    fn redis_lookup_injects_remote_value_into_snapshot() {
        let json = serde_json::json!({});
        let mut mock = MockExternal::default();
        mock.redis.insert(
            "feature:x".into(),
            serde_json::json!(42).to_string(),
        );

        let rule = RuleExpr::RedisCompareLeaf {
            id: "redis.leaf".into(),
            redis_key: "feature:x".into(),
            op: CompareOp::Eq,
            expected: json!(42),
        };

        let mut eval = Evaluator::new(rule, TraceContext::new(), mock, "test");
        let (decision, manifest) = eval.evaluate(&json);
        assert!(decision);
        let step = &manifest.expect("manifest").trace.expect("trace").steps[0];
        assert!(step.state_snapshot.contains_key("redis.value.raw"));
        assert_eq!(
            step.state_snapshot.get("redis.value.raw").map(String::as_str),
            Some("42")
        );
    }

    #[test]
    fn partial_manifest_on_external_failure() {
        let json = serde_json::json!({"id": "z"});
        let rule = RuleExpr::RedisCompareLeaf {
            id: "missing".into(),
            redis_key: "nope".into(),
            op: CompareOp::Eq,
            expected: json!(1),
        };

        let mut eval = Evaluator::new(rule, TraceContext::new(), MockExternal::default(), "test");
        let (decision, outcome) = eval.evaluate(&json);
        assert!(!decision);
        let partial = outcome.expect_err("partial");
        assert!(partial.failure_message.contains("missing key"));
        assert_eq!(partial.failing_rule_id.as_deref(), Some("missing"));
    }

    #[test]
    fn verified_rule_json_accepts_matching_content_id() {
        let raw = br#"{"kind":"compare_leaf","id":"x","path":"/a","op":"eq","expected":1}"#;
        let hex_id = hex::encode(rule_content_sha256(raw));
        Evaluator::try_from_verified_rule_json(
            raw,
            &hex_id,
            TraceContext::new(),
            MockExternal::default(),
            "test",
        )
        .expect("matching hash must load");
    }

    #[test]
    fn verified_rule_json_rejects_wrong_content_id() {
        let raw = br#"{"kind":"compare_leaf","id":"x","path":"/a","op":"eq","expected":1}"#;
        let wrong = "00".repeat(32);
        match Evaluator::try_from_verified_rule_json(
            raw,
            &wrong,
            TraceContext::new(),
            MockExternal::default(),
            "test",
        ) {
            Ok(_) => panic!("wrong hash must fail"),
            Err(e) => assert!(matches!(
                e,
                crate::engine::rule_address::SecurityIntegrityViolation::ContentHashMismatch { .. }
            )),
        }
    }

    #[test]
    fn graph_match_triggers_block_when_context_graph_score_exceeds_threshold() {
        let rule = RuleExpr::GraphMatch {
            id: "graph-risk".into(),
            threshold: 0.8,
        };
        let mut eval = Evaluator::new(rule, TraceContext::new(), MockExternal::default(), "test");
        let (decision, manifest) = eval.evaluate(&json!({"context": {"graph_score": 0.85}}));
        assert!(
            decision,
            "graph_score 0.85 > 0.8 ⇒ rule passes (decision true / block path)"
        );
        let m = manifest.expect("manifest");
        let step = &m.trace.expect("trace").steps[0];
        assert_eq!(step.logic_operator, "GRAPH_MATCH");
        assert!(step.result);
    }

    #[test]
    fn graph_match_no_block_when_score_not_above_threshold() {
        let rule = RuleExpr::GraphMatch {
            id: "g".into(),
            threshold: 0.8,
        };
        let mut eval = Evaluator::new(rule, TraceContext::new(), MockExternal::default(), "test");
        let (decision, _) = eval.evaluate(&json!({"context": {"graph_score": 0.79}}));
        assert!(!decision);
    }

    #[derive(serde::Deserialize)]
    struct FlatGraphScoreRule {
        op: String,
        field: String,
        val: serde_json::Number,
    }

    fn rule_expr_from_flat_graph_score_gate(
        cond: FlatGraphScoreRule,
        id: impl Into<String>,
    ) -> Option<RuleExpr> {
        if cond.op == "gt" && cond.field == "graph_score" {
            let threshold = cond.val.as_f64()?;
            Some(RuleExpr::GraphMatch {
                id: id.into(),
                threshold,
            })
        } else {
            None
        }
    }

    /// Gate: rule shape ``{ "op": "gt", "field": "graph_score", "val": 0.8 }`` blocks when score is high enough.
    #[test]
    fn flat_json_op_gt_field_graph_score_val_triggers_block() {
        let flat = json!({"op": "gt", "field": "graph_score", "val": 0.8});
        let cond: FlatGraphScoreRule = serde_json::from_value(flat).expect("deserialize flat rule");
        let rule = rule_expr_from_flat_graph_score_gate(cond, "leaf.graph").expect("map to GraphMatch");
        let mut eval = Evaluator::new(rule, TraceContext::new(), MockExternal::default(), "test");
        let (decision, manifest) = eval.evaluate(&json!({"context": {"graph_score": 0.81}}));
        assert!(decision);
        let step = &manifest.expect("manifest").trace.expect("trace").steps[0];
        assert_eq!(step.rule_id, "leaf.graph");
        assert!(step.result);
    }

    #[test]
    fn verified_rule_json_accepts_graph_match_kind() {
        let raw = br#"{"kind":"graph_match","id":"gm","threshold":0.5}"#;
        let hex_id = hex::encode(rule_content_sha256(raw));
        let expr = parse_verified_rule_json(raw, &hex_id).expect("parse graph_match");
        let RuleExpr::GraphMatch { threshold, .. } = expr else {
            panic!("expected GraphMatch");
        };
        assert!((threshold - 0.5).abs() < f64::EPSILON);
        let mut eval = Evaluator::try_from_verified_rule_json(
            raw,
            &hex_id,
            TraceContext::new(),
            MockExternal::default(),
            "test",
        )
        .expect("evaluator");
        let (decision, _) = eval.evaluate(&json!({"context": {"graph_score": 0.6}}));
        assert!(decision);
    }
}
