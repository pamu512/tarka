//! Load typed signal identifiers from a central JSON registry file.

use serde::Deserialize;
use std::collections::btree_map::Entry;
use std::collections::BTreeMap;
use std::fs;
use std::path::Path;

use super::error::CompileError;
use super::signal_type::SignalType;

/// Metadata required for each registered signal (must include a logical [`SignalType`]).
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct SignalMeta {
    pub signal_type: SignalType,
}

/// JSON-backed registry: each signal name maps to its declared [`SignalType`] for compile-time checks.
#[derive(Debug, Clone)]
pub struct SignalRegistry {
    signals: BTreeMap<String, SignalMeta>,
}

#[derive(Deserialize)]
struct RegistryEnvelope {
    #[serde(default)]
    signals: Option<serde_json::Value>,
}

impl SignalRegistry {
    /// Load registry from a UTF-8 JSON file (typed schema only).
    pub fn from_json_file(path: impl AsRef<Path>) -> Result<Self, CompileError> {
        let path = path.as_ref();
        let bytes = fs::read(path).map_err(|e| CompileError::validation(
            format!(
                "failed to read SignalRegistry file {}: {e}",
                path.display()
            ),
            None,
        ))?;
        Self::from_json_bytes(&bytes)
    }

    /// Parse typed registry JSON.
    ///
    /// Supported shapes:
    /// - `{ "signals": { "name": { "type": "integer", ... }, ... } }`
    /// - `{ "signals": [ { "name": "x", "type": "boolean" }, ... ] }`
    ///
    /// Plain string arrays (name-only) are rejected — every signal must declare a `type`.
    pub fn from_json_bytes(bytes: &[u8]) -> Result<Self, CompileError> {
        let root: RegistryEnvelope = serde_json::from_slice(bytes).map_err(|e| {
            CompileError::validation(format!("SignalRegistry JSON is invalid: {e}"), None)
        })?;
        let Some(raw) = root.signals else {
            return Err(CompileError::validation(
                "SignalRegistry JSON must contain a top-level \"signals\" field",
                None,
            ));
        };

        let mut signals = BTreeMap::new();

        match raw {
            serde_json::Value::Array(arr) => {
                for (i, v) in arr.iter().enumerate() {
                    let obj = v.as_object().ok_or_else(|| {
                        CompileError::validation(
                            format!(
                                "SignalRegistry `signals[{i}]` must be an object with `name` and `type`"
                            ),
                            None,
                        )
                    })?;
                    let name = obj
                        .get("name")
                        .and_then(|x| x.as_str())
                        .filter(|s| !s.is_empty())
                        .ok_or_else(|| {
                            CompileError::validation(
                                format!("SignalRegistry `signals[{i}].name` must be a non-empty string"),
                                None,
                            )
                        })?;
                    let ty_raw = obj.get("type").and_then(|x| x.as_str()).ok_or_else(|| {
                        CompileError::validation(
                            format!("SignalRegistry `signals[{i}]` must include string field `type`"),
                            None,
                        )
                    })?;
                    let st = SignalType::from_json_str(ty_raw).ok_or_else(|| {
                        CompileError::validation(
                            format!(
                                "SignalRegistry unknown type `{ty_raw}` for signal `{name}` (use integer, float, boolean, string, list)"
                            ),
                            None,
                        )
                    })?;
                    match signals.entry(name.to_string()) {
                        Entry::Vacant(v) => {
                            v.insert(SignalMeta { signal_type: st });
                        }
                        Entry::Occupied(_) => {
                            return Err(CompileError::validation(
                                format!("duplicate signal name `{name}` in registry"),
                                None,
                            ));
                        }
                    }
                }
            }
            serde_json::Value::Object(map) => {
                for (name, v) in map {
                    if name.is_empty() {
                        continue;
                    }
                    let obj = v.as_object().ok_or_else(|| {
                        CompileError::validation(
                            format!(
                                "SignalRegistry entry `{name}` must be an object with a `type` field"
                            ),
                            None,
                        )
                    })?;
                    let ty_raw = obj.get("type").and_then(|x| x.as_str()).ok_or_else(|| {
                        CompileError::validation(
                            format!("SignalRegistry `{name}` must include string field `type`"),
                            None,
                        )
                    })?;
                    let st = SignalType::from_json_str(ty_raw).ok_or_else(|| {
                        CompileError::validation(
                            format!(
                                "SignalRegistry unknown type `{ty_raw}` for signal `{name}` (use integer, float, boolean, string, list)"
                            ),
                            None,
                        )
                    })?;
                    match signals.entry(name.clone()) {
                        Entry::Vacant(v) => {
                            v.insert(SignalMeta { signal_type: st });
                        }
                        Entry::Occupied(_) => {
                            return Err(CompileError::validation(
                                format!("duplicate signal name `{name}` in registry"),
                                None,
                            ));
                        }
                    }
                }
            }
            serde_json::Value::String(_) => {
                return Err(CompileError::validation(
                    "typed SignalRegistry requires `signals` to be an object or array of `{name, type}` entries (legacy string entries are not supported)",
                    None,
                ));
            }
            _ => {
                return Err(CompileError::validation(
                    "`signals` must be a JSON array or object",
                    None,
                ));
            }
        }

        if signals.is_empty() {
            return Err(CompileError::validation(
                "SignalRegistry contains no signals",
                None,
            ));
        }

        Ok(Self { signals })
    }

    #[inline]
    pub fn contains(&self, name: &str) -> bool {
        self.signals.contains_key(name)
    }

    #[inline]
    pub fn signal_type(&self, name: &str) -> Option<SignalType> {
        self.signals.get(name).map(|m| m.signal_type)
    }

    pub fn meta(&self, name: &str) -> Option<&SignalMeta> {
        self.signals.get(name)
    }

    /// Sorted signal names (for suggestions / diagnostics).
    pub fn names(&self) -> impl Iterator<Item = &str> {
        self.signals.keys().map(|s| s.as_str())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn loads_example_registry_json() {
        let bytes = include_bytes!("../../data/signal_registry.example.json");
        let reg = SignalRegistry::from_json_bytes(bytes).expect("example registry");
        assert!(reg.contains("payment.amount"));
        assert_eq!(
            reg.signal_type("payment.amount"),
            Some(SignalType::Integer)
        );
        assert!(!reg.contains("missing.signal"));
    }
}
