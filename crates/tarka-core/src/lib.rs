//! Core protobuf-backed models shared across Tarka components.

/// Wire-format evidence types generated from `proto/tarka/evidence/wire/v1/evidence.proto` (`tarka.evidence.wire.v1`).
pub mod pb {
    #![allow(clippy::all)]
    #![allow(dead_code)]
    #![allow(missing_docs)]
    #![allow(non_snake_case)]
    include!(concat!(
        env!("OUT_DIR"),
        "/tarka.evidence.wire.v1.rs"
    ));
}

pub mod compiler;
pub mod crypto;
pub mod engine;
pub mod evidence;
pub mod metrics_export;
pub mod observability;
pub mod tracing_elk;

mod loki_tee;

pub use observability::{
    init_tracer, shutdown_tracer, ObservabilityError, DEFAULT_OTEL_SERVICE_NAME,
    DEFAULT_OTLP_GRPC_ENDPOINT,
};
#[cfg(feature = "prometheus")]
pub use metrics_export::{install_prometheus_exporter, PrometheusInstallError};

pub use crypto::{
    canonical_step_bytes, generate_proof, generate_proof_and_sign, merkle_root,
    trace_leaf_digests, try_local_ed25519_ph_signer_from_env, verifying_key_from_env,
    verify_manifest, verify_manifest_with_key,
    CryptoError, KmsConnectionError, KmsSigner, LocalEd25519PhSigner, MerkleHasher, MerkleProof,
    ProofSignError, Signer, SigningError, VerifyError,
};

pub use compiler::{
    compile_yaml_rule_set, type_check_expr, CompileError, CompiledRule, RuleExpression, RuleSet,
    ScalarValue, SignalCompareLeaf, SignalMeta, SignalRegistry, SignalType, TypeChecker, YamlExpr,
};

pub use engine::{
    engine_fingerprint, normalize_otel_span_id, normalize_otel_trace_id, parse_verified_rule_json,
    random_w3c_trace_id,
    rule_content_sha256, rule_expr_to_mermaid_flowchart, validate_wasm_bytes_for_custom_rule,
    verify_rule_content, verify_rule_content_hex, Clock, ContentAddressedRuleStore, EvaluateOutcome,
    Evaluator, FixedClock, LoadedRuleSnapshot, MermaidFlowchartError, OtelSpanIdError, OtelTraceIdError,
    PartialManifest, RuleContentId, RuleExpr, RuleManager, RuleManagerError, RuleManagerOptions,
    ReloadOutcome, RuleAuditMode, SecurityIntegrityViolation, CriticalRuleLoadAlert, CriticalAlertReason,
    DirectoryScanResult, scan_merge_directory,
    SharedClock, SystemClock, TraceContext, WasmModuleBytesRegistry, WasmRegistryError,
    WasmSandboxConfig, WasmSandboxError, MAX_CUSTOM_RULE_WASM_MEMORY_BYTES, MAX_MERMAID_DEPTH,
    MAX_MERMAID_NODES,
};
