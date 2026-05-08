//! PyO3 bridge: **wire** protobuf manifests (`PyBytes`) plus optional sealing when `fast_path` is disabled.
//! When not using `fast_path`, the Rust runtime seals via **`FileKeyStore`** (default path `/etc/tarka/keys/engine.priv`,
//! override with **`TARKA_ENGINE_PRIVATE_KEY_PATH`**) before returning to Python.
//!
//! Sealing / Merkle / signal-hash failures from `tarka_core` map to Python
//! `tarka.verifier.ManifestIntegrityError` with `failure_reason: VerificationFailureReason` (not a bare
//! `RuntimeError`).
//!
//! Ingress admission (token bucket + bounded concurrency) is configured via environment variables
//! documented on [`crate::ingest`].

mod ingest;

use pyo3::exceptions::{PyException, PyRuntimeError, PyTypeError, PyValueError};
use pyo3::types::{
    PyAnyMethods, PyBytes, PyDict, PyDictMethods, PyList, PyListMethods, PyModule, PyModuleMethods,
    PyTuple,
};
use pyo3::{
    pyclass, pyfunction, pymethods, pymodule, wrap_pyfunction, Bound, PyErr, PyResult, Python,
};
use std::collections::HashMap;
use std::num::ParseIntError;
use std::sync::{Arc, OnceLock};

use opentelemetry::trace::{
    SpanContext, SpanId, TraceContextExt, TraceFlags, TraceId, TraceState,
};
use opentelemetry::Context;
use tarka_core::engine::{
    encode_wire_manifest, finalize_decision_with_optional_seal, normalize_otel_span_id,
    normalize_otel_trace_id, random_w3c_trace_id, rule_expr_to_mermaid_flowchart, Evaluator,
    FileKeyStore, FixedClock, MockExternal, RuleExpr, RuntimeError, SharedClock, TraceContext,
    system_clock,
};
use tarka_core::evidence::merkle::TraceMerkleError;
use tarka_core::evidence::EvidenceError;
use tarka_core::{rule_content_sha256, SecurityIntegrityViolation};
use tracing_opentelemetry::OpenTelemetrySpanExt;

pyo3::create_exception!(_tarka, BackpressureSignal, PyException);

static INGEST_GATE: OnceLock<ingest::IngestGate> = OnceLock::new();

fn ingest_gate() -> &'static ingest::IngestGate {
    INGEST_GATE.get_or_init(|| {
        let gate = ingest::IngestGate::from_env_first_call();
        ingest::spawn_shutdown_signal_handler(gate.inner_arc());
        gate
    })
}

/// Snapshot of the ingestion gate (capacity, in-flight). For metrics and health checks.
#[pyfunction]
fn ingest_stats(py: Python<'_>) -> PyResult<Bound<'_, PyDict>> {
    let g = ingest_gate();
    let d = PyDict::new(py);
    d.set_item("capacity", g.capacity())?;
    d.set_item("in_flight", g.in_flight())?;
    d.set_item("token_refill_per_sec", g.token_refill_per_sec())?;
    d.set_item("buffer_pressure_percent", ingest::BUFFER_PRESSURE_PERCENT)?;
    d.set_item("accepting_new_requests", g.accepting_new_requests())?;
    d.set_item("shutdown_grace_secs", ingest::SHUTDOWN_GRACE_SECS)?;
    d.set_item("env_buffer_capacity", ingest::ENV_BUFFER_CAPACITY)?;
    d.set_item("env_token_refill_per_sec", ingest::ENV_TOKEN_REFILL_PER_SEC)?;
    d.set_item("env_token_burst", ingest::ENV_TOKEN_BURST)?;
    Ok(d)
}

fn otel_parse_err(field: &str, source: ParseIntError) -> PyErr {
    PyErr::new::<PyValueError, _>(format!("{field} is not valid hexadecimal: {source}"))
}

/// Failures from [`evaluate_inner_owned`] that must be mapped to Python **after** releasing the GIL.
enum EvaluateFailure {
    Integrity(SecurityIntegrityViolation),
    Finalize(RuntimeError),
}

/// Combines Python-level validation errors with Rust FFI failures surfaced from the same thread pool section.
enum EvalErr {
    Py(PyErr),
    Ffi(EvaluateFailure),
}

/// Structured FFI error using Python :class:`tarka.verifier.ManifestIntegrityError`.
fn manifest_integrity_err(py: Python<'_>, variant: &'static str, detail: String) -> PyErr {
    let Ok(m) = py.import("tarka.verifier") else {
        return PyErr::new::<PyRuntimeError, _>(detail);
    };
    let Ok(cls) = m.getattr("ManifestIntegrityError") else {
        return PyErr::new::<PyRuntimeError, _>(detail);
    };
    let Ok(enum_cls) = m.getattr("VerificationFailureReason") else {
        return PyErr::new::<PyRuntimeError, _>(detail);
    };
    let Ok(member) = enum_cls.getattr(variant) else {
        return PyErr::new::<PyRuntimeError, _>(detail);
    };
    let kwargs = PyDict::new(py);
    if kwargs.set_item("failure_reason", &member).is_err() {
        return PyErr::new::<PyRuntimeError, _>(detail);
    }
    let args = match PyTuple::new(py, [detail.as_str()]) {
        Ok(t) => t,
        Err(_) => return PyErr::new::<PyRuntimeError, _>(detail),
    };
    let obj = match cls.call(args, Some(&kwargs)) {
        Ok(o) => o,
        Err(e) => return e,
    };
    PyErr::from_value(obj)
}

fn security_integrity_to_py(py: Python<'_>, e: SecurityIntegrityViolation) -> PyErr {
    manifest_integrity_err(py, "CANONICALIZATION_ERROR", e.to_string())
}

fn runtime_error_to_manifest_integrity(py: Python<'_>, e: RuntimeError) -> PyErr {
    let detail = e.to_string();
    let variant = match &e {
        RuntimeError::Seal(se) => match se {
            EvidenceError::Signature(_) => "SIGNATURE_MISMATCH",
            EvidenceError::MissingEngine => "ENGINE_METADATA_MISSING",
            EvidenceError::DigestLength => "INVALID_SEAL_FIELDS",
            EvidenceError::SignalHash(_)
            | EvidenceError::TraceMerkle(_)
            | EvidenceError::TooLarge => "CANONICALIZATION_ERROR",
        },
        RuntimeError::TraceMerkleProof(te) => match te {
            TraceMerkleError::MerkleRootMissing => "INCOMPLETE_PROOF",
            TraceMerkleError::TooLarge | TraceMerkleError::SnapshotInvariant => {
                "CANONICALIZATION_ERROR"
            }
        },
        RuntimeError::Convert(_) => "DECODE_ERROR",
        RuntimeError::KeyStore(_) => "CANONICALIZATION_ERROR",
        RuntimeError::WireEncode(_) => "CANONICALIZATION_ERROR",
    };
    manifest_integrity_err(py, variant, detail)
}

fn evaluate_failure_to_py(py: Python<'_>, e: EvaluateFailure) -> PyErr {
    match e {
        EvaluateFailure::Integrity(v) => security_integrity_to_py(py, v),
        EvaluateFailure::Finalize(v) => runtime_error_to_manifest_integrity(py, v),
    }
}

fn eval_err_to_py(py: Python<'_>, e: EvalErr) -> PyErr {
    match e {
        EvalErr::Py(err) => err,
        EvalErr::Ffi(f) => evaluate_failure_to_py(py, f),
    }
}

/// Returns the lowercase hex SHA-256 digest of `rule_json` UTF-8 bytes (the content address).
#[pyfunction]
fn rule_content_id(rule_json: &str) -> String {
    hex::encode(rule_content_sha256(rule_json.as_bytes()))
}

/// Serialize a [`RuleExpr`] JSON tree as a Mermaid.js flowchart (``flowchart TD``) for analyst UIs.
#[pyfunction]
fn rule_expr_mermaid_flowchart(rule_json: &str) -> PyResult<String> {
    let expr: RuleExpr = serde_json::from_str(rule_json).map_err(|e| {
        PyErr::new::<PyValueError, _>(format!("invalid RuleExpr JSON: {e}"))
    })?;
    rule_expr_to_mermaid_flowchart(&expr).map_err(|e| PyErr::new::<PyValueError, _>(e.to_string()))
}

/// Holds **wire** protobuf bytes ([`tarka_core::pb::EvidenceManifest`]: `tarka.evidence.wire.v1`) and
/// optional detached signature bytes when sealed (`fast_path=false`).
///
/// Python code should prefer [`manifest_proto_bytes`](Self::manifest_proto_bytes) and decode lazily
/// (see the `tarka.decision.TarkaDecision` wrapper).
#[pyclass(name = "DecisionInner")]
pub struct DecisionInner {
    #[pyo3(get)]
    pub decision: bool,
    manifest_bytes: Vec<u8>,
    #[pyo3(get)]
    pub is_partial: bool,
    #[pyo3(get)]
    pub partial_error: Option<String>,
    #[pyo3(get)]
    pub failing_rule_id: Option<String>,
    /// True when the embedded wire manifest carries `merkle_proof` (Triple-DB / audit path).
    #[pyo3(get)]
    pub has_merkle_proof: bool,
    merkle_proof_bytes: Option<Vec<u8>>,
    merkle_signature_bytes: Option<Vec<u8>>,
}

#[pymethods]
impl DecisionInner {
    /// Raw protobuf (`tarka.evidence.wire.v1.EvidenceManifest`) suitable for lazy decoding on the Python side.
    fn manifest_proto_bytes<'py>(&self, py: Python<'py>) -> Bound<'py, PyBytes> {
        PyBytes::new(py, &self.manifest_bytes)
    }

    /// Serialized [`rs_merkle::MerkleProof`] (`to_bytes`) over **wire** trace leaves (same layout as
    /// [`tarka_core::evidence::merkle::try_calculate_trace_root`]). Empty bytes when `fast_path` was used;
    /// when sealed, may still be empty if the proof covers all leaves (no sibling hashes).
    fn merkle_proof_proto_bytes<'py>(&self, py: Python<'py>) -> Bound<'py, PyBytes> {
        PyBytes::new(py, self.merkle_proof_bytes.as_deref().unwrap_or(&[]))
    }

    fn merkle_signature_bytes<'py>(&self, py: Python<'py>) -> Option<Bound<'py, PyBytes>> {
        self.merkle_signature_bytes
            .as_ref()
            .map(|b| PyBytes::new(py, b))
    }
}

/// Evaluate `rule_json` + `data_json`, returning **wire** protobuf manifest bytes without JSON serialization.
///
/// `rule_content_id_hex` must equal the lowercase hex SHA-256 of `rule_json.encode('utf-8')`.
/// When `fast_path` is `True`, sealing (super-block hash + Ed25519ph) is skipped.
/// When `fast_path` is `False`, the engine reads `/etc/tarka/keys/engine.priv` (override with
/// **`TARKA_ENGINE_PRIVATE_KEY_PATH`**) and seals before returning.
///
/// `trace_id`: optional W3C OpenTelemetry trace id (exactly 32 hexadecimal characters). When omitted or
/// blank, a cryptographically random trace id is generated so every manifest step carries a correlation id.
///
/// `span_id`: optional W3C parent span id (exactly 16 hexadecimal characters). When set together with a
/// valid `trace_id`, the Rust `tracing` span for this evaluation is linked as a child of that remote
/// OpenTelemetry span (requires a `tracing-opentelemetry` layer in the host process).
///
/// `replay_wall_time_ns`: when set, nanoseconds since Unix epoch for [`FixedClock`] so audit replays and
/// time-dependent rules match a captured instant (production omits this and uses wall clock).
#[pyfunction]
#[pyo3(signature = (rule_json, data_json, rule_content_id_hex, fast_path=true, engine_version="tarka-core", trace_id=None, span_id=None, replay_wall_time_ns=None, mock_redis=None, mock_lists=None, mock_custom=None))]
#[allow(clippy::too_many_arguments)]
fn evaluate(
    py: Python<'_>,
    rule_json: &str,
    data_json: &str,
    rule_content_id_hex: &str,
    fast_path: bool,
    engine_version: &str,
    trace_id: Option<String>,
    span_id: Option<String>,
    replay_wall_time_ns: Option<u64>,
    mock_redis: Option<Bound<'_, PyDict>>,
    mock_lists: Option<Bound<'_, PyDict>>,
    mock_custom: Option<Bound<'_, PyDict>>,
) -> PyResult<DecisionInner> {
    let redis = if let Some(d) = mock_redis {
        dict_to_string_map(&d)?
    } else {
        HashMap::new()
    };
    let lists = if let Some(d) = mock_lists {
        dict_to_string_vec_map(&d)?
    } else {
        HashMap::new()
    };
    let customs = if let Some(d) = mock_custom {
        dict_to_bool_map(&d)?
    } else {
        HashMap::new()
    };
    match py.allow_threads(|| {
        evaluate_inner_owned(
            rule_json,
            data_json,
            rule_content_id_hex,
            fast_path,
            engine_version,
            trace_id,
            span_id,
            replay_wall_time_ns,
            redis,
            lists,
            customs,
        )
    }) {
        Ok(inner) => Ok(inner),
        Err(e) => Err(eval_err_to_py(py, e)),
    }
}

#[allow(clippy::too_many_arguments)]
fn evaluate_inner_owned(
    rule_json: &str,
    data_json: &str,
    rule_content_id_hex: &str,
    fast_path: bool,
    engine_version: &str,
    trace_id: Option<String>,
    span_id: Option<String>,
    replay_wall_time_ns: Option<u64>,
    redis: HashMap<String, String>,
    lists: HashMap<String, Vec<String>>,
    customs: HashMap<String, bool>,
) -> Result<DecisionInner, EvalErr> {
    let _ingest_admission = match ingest_gate().try_enter() {
        Ok(guard) => guard,
        Err(deny) => {
            let json = ingest::backpressure_json(&deny);
            return Err(EvalErr::Py(BackpressureSignal::new_err(json)));
        }
    };

    let data: serde_json::Value = serde_json::from_str(data_json).map_err(|e| {
        EvalErr::Py(PyErr::new::<PyValueError, _>(format!("invalid data_json: {e}")))
    })?;

    let mock = MockExternal {
        redis,
        lists,
        customs,
    };

    let normalized_trace = normalize_otel_trace_id(trace_id.as_deref()).map_err(|e| {
        EvalErr::Py(PyErr::new::<PyValueError, _>(e.to_string()))
    })?;
    let normalized_span = normalize_otel_span_id(span_id.as_deref()).map_err(|e| {
        EvalErr::Py(PyErr::new::<PyValueError, _>(e.to_string()))
    })?;

    if normalized_span.is_some() && normalized_trace.is_none() {
        return Err(EvalErr::Py(PyErr::new::<PyValueError, _>(
            "span_id requires a valid trace_id (32 hexadecimal characters); omit span_id or supply trace_id",
        )));
    }

    let otel_trace_id = normalized_trace
        .clone()
        .unwrap_or_else(random_w3c_trace_id);

    let remote_parent: Option<Context> = match (&normalized_trace, &normalized_span) {
        (Some(trace_hex), Some(span_hex)) => {
            let tid = TraceId::from_hex(trace_hex)
                .map_err(|e| EvalErr::Py(otel_parse_err("trace_id", e)))?;
            let sid = SpanId::from_hex(span_hex)
                .map_err(|e| EvalErr::Py(otel_parse_err("span_id", e)))?;
            let span_ctx = SpanContext::new(
                tid,
                sid,
                TraceFlags::SAMPLED,
                true,
                TraceState::NONE,
            );
            if !span_ctx.is_valid() {
                return Err(EvalErr::Py(PyErr::new::<PyValueError, _>(
                    "trace_id and span_id must be non-zero W3C identifiers",
                )));
            }
            Some(Context::new().with_remote_span_context(span_ctx))
        }
        _ => None,
    };

    let span = tracing::span!(tracing::Level::INFO, "tarka_py.evaluate");
    if let Some(ref parent) = remote_parent {
        if let Err(e) = span.set_parent(parent.clone()) {
            tracing::debug!(
                target: "tarka_py",
                error = %e,
                "OpenTelemetry parent not applied (tracing subscriber may lack tracing-opentelemetry layer)"
            );
        }
    }
    let _evaluate_span = span.enter();

    let clock: SharedClock = match replay_wall_time_ns {
        Some(ns) => Arc::new(FixedClock::from_unix_nanos(u128::from(ns))),
        None => system_clock(),
    };
    let trace = TraceContext::with_clock_and_otel(clock, Some(otel_trace_id));

    let mut evaluator = Evaluator::try_from_verified_rule_json(
        rule_json.as_bytes(),
        rule_content_id_hex,
        trace,
        mock,
        engine_version.to_string(),
    )
    .map_err(|e| EvalErr::Ffi(EvaluateFailure::Integrity(e)))?;

    let key_store = FileKeyStore::from_env_or_default();
    let finalized = finalize_decision_with_optional_seal(&mut evaluator, &data, fast_path, &key_store)
        .map_err(|e| EvalErr::Ffi(EvaluateFailure::Finalize(e)))?;

    let manifest_bytes = encode_wire_manifest(&finalized.wire_manifest)
        .map_err(|e| EvalErr::Ffi(EvaluateFailure::Finalize(e)))?;

    let (partial_error, failing_rule_id, is_partial) = match &finalized.partial_error {
        Some(msg) => (
            Some(msg.clone()),
            finalized.failing_rule_id.clone(),
            true,
        ),
        None => (None, None, false),
    };

    let merkle_proof_bytes = finalized.wire_manifest.merkle_proof.clone();
    let has_merkle_proof = merkle_proof_bytes.is_some();
    let merkle_signature_bytes = if finalized.sealed {
        Some(finalized.wire_manifest.signature.clone())
    } else {
        None
    };

    Ok(DecisionInner {
        decision: finalized.decision,
        manifest_bytes,
        is_partial,
        partial_error,
        failing_rule_id,
        has_merkle_proof,
        merkle_proof_bytes,
        merkle_signature_bytes,
    })
}

fn dict_to_string_map(d: &Bound<'_, PyDict>) -> PyResult<HashMap<String, String>> {
    let mut out = HashMap::new();
    for (k, v) in d.iter() {
        let key: String = k.extract()?;
        let value: String = v.extract().map_err(|_| {
            PyErr::new::<PyTypeError, _>(format!(
                "mock_redis[{key:?}] expected str value"
            ))
        })?;
        out.insert(key, value);
    }
    Ok(out)
}

fn dict_to_string_vec_map(d: &Bound<'_, PyDict>) -> PyResult<HashMap<String, Vec<String>>> {
    let mut out = HashMap::new();
    for (k, v) in d.iter() {
        let key: String = k.extract()?;
        let list = v.downcast::<PyList>().map_err(|_| {
            PyErr::new::<PyTypeError, _>(format!(
                "mock_lists[{key:?}] expected list"
            ))
        })?;
        let mut items = Vec::with_capacity(list.len());
        for item in list.iter() {
            items.push(item.extract::<String>().map_err(|_| {
                PyErr::new::<PyTypeError, _>("mock_lists entries must be lists of strings")
            })?);
        }
        out.insert(key, items);
    }
    Ok(out)
}

fn dict_to_bool_map(d: &Bound<'_, PyDict>) -> PyResult<HashMap<String, bool>> {
    let mut out = HashMap::new();
    for (k, v) in d.iter() {
        let key: String = k.extract()?;
        let value: bool = v.extract().map_err(|_| {
            PyErr::new::<PyTypeError, _>(format!(
                "mock_custom[{key:?}] expected bool"
            ))
        })?;
        out.insert(key, value);
    }
    Ok(out)
}

#[pymodule]
fn _tarka(py: Python<'_>, m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<DecisionInner>()?;
    m.add_function(wrap_pyfunction!(evaluate, m)?)?;
    m.add_function(wrap_pyfunction!(rule_content_id, m)?)?;
    m.add_function(wrap_pyfunction!(rule_expr_mermaid_flowchart, m)?)?;
    m.add_function(wrap_pyfunction!(ingest_stats, m)?)?;
    m.add(
        "BackpressureSignal",
        py.get_type::<BackpressureSignal>(),
    )?;
    Ok(())
}
