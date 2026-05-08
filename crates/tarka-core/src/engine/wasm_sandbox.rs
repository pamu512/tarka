//! Sandboxed execution of **complex custom rule** WebAssembly guests via Wasmtime.
//!
//! Guests must be **fully self-contained**: zero imports (no WASI, no host capabilities).
//! Host supplies UTF-8 JSON input through exported linear memory and calls a boolean export.
//!
//! ## Guest ABI
//!
//! - Exported [`memory`] (WebAssembly linear memory).
//! - Exported function `(export_name)` with signature `(i32, i32) -> i32`:
//!   - `input_ptr`, `input_len` describe the UTF-8 JSON payload region in guest memory.
//!   - Return `1` for true, `0` for false; any other value is rejected.
//!
//! [`memory`]: https://webassembly.github.io/spec/core/syntax/modules.html#memories

use std::sync::Arc;

use anyhow::Error as AnyhowError;
use thiserror::Error;
use wasmtime::{
    Config, Engine, Instance, Memory, Module, Store, StoreLimits, StoreLimitsBuilder, Trap,
};

/// Hard upper bound for each guest linear memory (10 MiB).
pub const MAX_CUSTOM_RULE_WASM_MEMORY_BYTES: usize = 10 * 1024 * 1024;

/// Default fuel budget for one guest invocation (CPU bounding).
pub const DEFAULT_WASM_FUEL_UNITS: u64 = 200_000;

/// Location in guest memory where the host writes JSON input (bytes `[base, base+len)`).
const GUEST_INPUT_BASE: u32 = 1024;

/// Tunables for the Wasmtime store backing a single evaluation.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct WasmSandboxConfig {
    pub max_linear_memory_bytes: usize,
    pub fuel_units: u64,
}

impl Default for WasmSandboxConfig {
    fn default() -> Self {
        Self {
            max_linear_memory_bytes: MAX_CUSTOM_RULE_WASM_MEMORY_BYTES,
            fuel_units: DEFAULT_WASM_FUEL_UNITS,
        }
    }
}

impl WasmSandboxConfig {
    /// Production-style defaults: 10 MiB memory cap and finite fuel.
    pub fn strict_default() -> Self {
        Self::default()
    }
}

/// Failure loading or executing a sandboxed rule module.
#[derive(Debug, Error)]
pub enum WasmSandboxError {
    #[error("invalid WebAssembly binary: {0}")]
    InvalidBinary(String),
    #[error("sandbox modules must not declare imports (found {count})")]
    ForbiddenImports { count: u32 },
    #[error("memory64 linear memory is not supported for custom rules")]
    UnsupportedMemory64,
    #[error("declared initial linear memory ({initial_bytes} bytes) exceeds limit ({max_bytes} bytes)")]
    InitialMemoryTooLarge {
        initial_bytes: u128,
        max_bytes: usize,
    },
    #[error("declared memory maximum ({max_bytes} bytes) exceeds limit ({limit_bytes} bytes)")]
    DeclaredMaxMemoryTooLarge {
        max_bytes: u128,
        limit_bytes: usize,
    },
    #[error("WebAssembly compile error: {0}")]
    Compile(String),
    #[error("WebAssembly instantiate error: {0}")]
    Instantiate(String),
    #[error("missing required export `{name}`")]
    MissingExport { name: String },
    #[error("input JSON size ({size} bytes) cannot be placed within linear memory budget")]
    InputTooLarge { size: usize },
    #[error("guest returned invalid boolean code {code} (expected 0 or 1)")]
    InvalidDecision { code: i32 },
    #[error("WebAssembly execution trapped: {0}")]
    ExecutionTrap(String),
    #[error("WebAssembly fuel exhausted")]
    OutOfFuel,
    #[error("guest linear memory operation failed: {0}")]
    Memory(String),
    #[error("Wasmtime store configuration failed: {0}")]
    StoreConfiguration(String),
}

/// Preflight validation: reject imports, memory64, and memories whose declared bounds exceed the cap.
pub fn validate_wasm_bytes_for_custom_rule(
    wasm_bytes: &[u8],
    max_linear_memory_bytes: usize,
) -> Result<(), WasmSandboxError> {
    let parser = wasmparser::Parser::new(0);
    for payload in parser.parse_all(wasm_bytes) {
        let payload = payload.map_err(|e| WasmSandboxError::InvalidBinary(e.to_string()))?;
        match payload {
            wasmparser::Payload::ImportSection(reader) => {
                let mut count = 0u32;
                for imp in reader {
                    let _ = imp.map_err(|e| WasmSandboxError::InvalidBinary(e.to_string()))?;
                    count += 1;
                }
                if count > 0 {
                    return Err(WasmSandboxError::ForbiddenImports { count });
                }
            }
            wasmparser::Payload::MemorySection(reader) => {
                for mem in reader {
                    let mt = mem.map_err(|e| WasmSandboxError::InvalidBinary(e.to_string()))?;
                    if mt.memory64 {
                        return Err(WasmSandboxError::UnsupportedMemory64);
                    }
                    let page_size = mt
                        .page_size_log2
                        .map(|l| 1u128 << u128::from(l))
                        .unwrap_or(65_536);
                    let initial_bytes = u128::from(mt.initial).saturating_mul(page_size);
                    if initial_bytes > max_linear_memory_bytes as u128 {
                        return Err(WasmSandboxError::InitialMemoryTooLarge {
                            initial_bytes,
                            max_bytes: max_linear_memory_bytes,
                        });
                    }
                    if let Some(max_pages) = mt.maximum {
                        let max_mem = u128::from(max_pages).saturating_mul(page_size);
                        if max_mem > max_linear_memory_bytes as u128 {
                            return Err(WasmSandboxError::DeclaredMaxMemoryTooLarge {
                                max_bytes: max_mem,
                                limit_bytes: max_linear_memory_bytes,
                            });
                        }
                    }
                }
            }
            _ => {}
        }
    }
    Ok(())
}

#[derive(Error, Debug)]
pub enum WasmRegistryError {
    #[error(transparent)]
    InvalidModuleId(#[from] crate::engine::rule_address::SecurityIntegrityViolation),
    #[error("wasm bytes SHA-256 mismatch for registry key `{expected_hex}`: computed `{actual_hex}`")]
    DigestMismatch {
        expected_hex: String,
        actual_hex: String,
    },
    #[error(transparent)]
    Preflight(#[from] WasmSandboxError),
    #[error("WebAssembly compile failed for `{module_hex}`: {message}")]
    Compile {
        module_hex: String,
        message: String,
    },
    #[error("failed to initialize Wasmtime engine: {0}")]
    Engine(String),
}

struct LimiterState {
    limits: StoreLimits,
}

/// Verified registry: maps lowercase SHA-256 hex id → raw wasm bytes. Keys must match [`crate::engine::rule_address::rule_content_sha256`].
pub type WasmModuleBytesRegistry = std::collections::HashMap<String, Arc<[u8]>>;

/// Compile-time verified and precompiled modules keyed by lowercase SHA-256 hex digest.
pub(crate) struct WasmRuntimeState {
    pub(crate) engine: Arc<Engine>,
    pub(crate) modules: std::collections::HashMap<String, Arc<Module>>,
    pub(crate) config: WasmSandboxConfig,
}

impl WasmRuntimeState {
    /// Builds runtime state: verifies each digest, preflights wasm, compiles modules.
    pub(crate) fn from_verified_registry(
        registry: WasmModuleBytesRegistry,
        config: WasmSandboxConfig,
    ) -> Result<Self, WasmRegistryError> {
        debug_assert!(!registry.is_empty(), "empty registry should use Evaluator without wasm");

        let engine = Arc::new(build_engine()?);

        let mut modules = std::collections::HashMap::new();
        for (hex_key, bytes) in registry {
            let id = crate::engine::rule_address::RuleContentId::parse_hex(&hex_key)?;
            let expected_hex = id.to_hex();
            let actual = crate::engine::rule_address::rule_content_sha256(bytes.as_ref());
            if actual != *id.as_bytes() {
                return Err(WasmRegistryError::DigestMismatch {
                    expected_hex: expected_hex.clone(),
                    actual_hex: hex::encode(actual),
                });
            }

            validate_wasm_bytes_for_custom_rule(bytes.as_ref(), config.max_linear_memory_bytes)?;

            let compiled = Module::from_binary(&engine, bytes.as_ref()).map_err(|e| {
                WasmRegistryError::Compile {
                    module_hex: expected_hex.clone(),
                    message: format!("{e:#}"),
                }
            })?;

            modules.insert(expected_hex, Arc::new(compiled));
        }

        Ok(Self {
            engine,
            modules,
            config,
        })
    }
}

fn build_engine() -> Result<Engine, WasmRegistryError> {
    let mut cfg = Config::new();
    cfg.consume_fuel(true);
    cfg.cranelift_nan_canonicalization(true);
    Engine::new(&cfg).map_err(|e| WasmRegistryError::Engine(format!("{e:#}")))
}

/// Runs the compiled guest `evaluate` export against JSON input.
pub(crate) fn evaluate_json_with_module(
    engine: &Engine,
    module: &Module,
    config: &WasmSandboxConfig,
    export_name: &str,
    input: &serde_json::Value,
) -> Result<bool, WasmSandboxError> {
    let payload = serde_json::to_string(input).map_err(|e| WasmSandboxError::InvalidBinary(e.to_string()))?;
    let payload_bytes = payload.as_bytes();

    let limits = StoreLimitsBuilder::new()
        .memory_size(config.max_linear_memory_bytes)
        .instances(1)
        .memories(1)
        .tables(256)
        .build();

    let mut store = Store::new(
        engine,
        LimiterState {
            limits,
        },
    );

    store.limiter(|s: &mut LimiterState| &mut s.limits);
    store
        .set_fuel(config.fuel_units)
        .map_err(|e| WasmSandboxError::StoreConfiguration(format!("{e:#}")))?;

    let instance = Instance::new(&mut store, module, &[]).map_err(|e| {
        WasmSandboxError::Instantiate(format!("{e:#}"))
    })?;

    let memory = instance
        .get_memory(&mut store, "memory")
        .ok_or_else(|| WasmSandboxError::MissingExport {
            name: "memory".into(),
        })?;

    ensure_guest_input_region(&mut store, &memory, payload_bytes.len(), config.max_linear_memory_bytes)?;

    memory
        .write(&mut store, GUEST_INPUT_BASE as usize, payload_bytes)
        .map_err(|e| WasmSandboxError::Memory(format!("{e:#}")))?;

    let evaluate = instance
        .get_typed_func::<(i32, i32), i32>(&mut store, export_name)
        .map_err(|_| WasmSandboxError::MissingExport {
            name: export_name.to_string(),
        })?;

    let call_result = evaluate.call(&mut store, (GUEST_INPUT_BASE as i32, payload_bytes.len() as i32));

    match call_result {
        Ok(code) => match code {
            0 => Ok(false),
            1 => Ok(true),
            other => Err(WasmSandboxError::InvalidDecision { code: other }),
        },
        Err(e) => Err(map_call_error(e)),
    }
}

fn ensure_guest_input_region<T>(
    store: &mut Store<T>,
    memory: &Memory,
    input_len: usize,
    max_linear_memory_bytes: usize,
) -> Result<(), WasmSandboxError> {
    let needed = (GUEST_INPUT_BASE as usize).saturating_add(input_len);
    if needed > max_linear_memory_bytes {
        return Err(WasmSandboxError::InputTooLarge { size: input_len });
    }

    let page_size = memory.page_size(&mut *store) as usize;
    let mut current = memory.data_size(&mut *store);
    if needed > current {
        let delta = needed - current;
        let pages = (delta + page_size - 1) / page_size;
        memory
            .grow(&mut *store, pages as u64)
            .map_err(|e| WasmSandboxError::Memory(format!("memory.grow: {e:#}")))?;
        current = memory.data_size(&mut *store);
        if needed > current {
            return Err(WasmSandboxError::Memory(
                "linear memory could not be grown to fit host input".into(),
            ));
        }
    }
    Ok(())
}

fn map_call_error(e: AnyhowError) -> WasmSandboxError {
    if let Some(t) = e.downcast_ref::<Trap>() {
        if *t == Trap::OutOfFuel {
            return WasmSandboxError::OutOfFuel;
        }
        return WasmSandboxError::ExecutionTrap(t.to_string());
    }
    WasmSandboxError::ExecutionTrap(format!("{e:#}"))
}
