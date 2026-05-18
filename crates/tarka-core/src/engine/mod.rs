//! Rule engine internals (evaluation tracing, etc.).

pub mod clock;
pub mod evaluator;
pub mod runtime;
pub mod mermaid_flowchart;
pub mod rule_manager;
pub mod node_identity;
pub mod otel_trace;
pub mod rule_address;
pub mod trace;
pub mod wasm_sandbox;

pub use evaluator::{
    parse_verified_rule_json, CompareOp, EvaluateOutcome, EvalFatalError, Evaluator,
    ExternalDataSource, ExternalError, JsonValue, MockExternal, PartialManifest, RuleExpr, RuleFail,
};
pub use mermaid_flowchart::{
    rule_expr_to_mermaid_flowchart, MermaidFlowchartError, MAX_MERMAID_DEPTH, MAX_MERMAID_NODES,
};
pub use wasm_sandbox::{
    validate_wasm_bytes_for_custom_rule, WasmModuleBytesRegistry, WasmRegistryError, WasmSandboxConfig,
    WasmSandboxError, MAX_CUSTOM_RULE_WASM_MEMORY_BYTES,
};
pub use node_identity::engine_fingerprint;
pub use rule_address::{
    rule_content_sha256, verify_rule_content, verify_rule_content_hex, ContentAddressedRuleStore,
    RuleContentId, SecurityIntegrityViolation,
};
pub use clock::{Clock, FixedClock, SharedClock, SystemClock, system_clock};
pub use otel_trace::{
    normalize_otel_span_id, normalize_otel_trace_id, random_w3c_trace_id, OtelSpanIdError,
    OtelTraceIdError,
};
pub use rule_manager::{
    scan_merge_directory, CriticalAlertReason, CriticalRuleLoadAlert, DirectoryScanResult,
    LoadedRuleSnapshot, ReloadOutcome, RuleAuditMode, RuleManager, RuleManagerError,
    RuleManagerOptions, SnapshotMeta,
};
pub use trace::{LogicFingerprint, TraceContext, TraceContextRegistry, TraceError, TraceStep};
pub use runtime::{
    encode_wire_manifest, finalize_decision_with_optional_seal, FileKeyStore, FinalizedWireDecision,
    KeyStore, KeyStoreError, LegacyWireConvertError, RuntimeError,
};
