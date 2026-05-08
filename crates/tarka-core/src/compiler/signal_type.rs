//! Logical signal types used by the registry and [`super::type_check::type_check_expr`].

/// Scalar / collection kinds for features ingested at evaluation time.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub enum SignalType {
    Integer,
    Float,
    Boolean,
    String,
    List,
}

impl SignalType {
    /// Stable display name for diagnostics (compile errors).
    #[must_use]
    pub fn label(self) -> &'static str {
        match self {
            SignalType::Integer => "Integer",
            SignalType::Float => "Float",
            SignalType::Boolean => "Boolean",
            SignalType::String => "String",
            SignalType::List => "List",
        }
    }

    pub(crate) fn from_json_str(s: &str) -> Option<Self> {
        let t = s.trim().to_ascii_lowercase();
        match t.as_str() {
            "integer" | "int" | "i64" => Some(SignalType::Integer),
            "float" | "double" | "f64" => Some(SignalType::Float),
            "boolean" | "bool" => Some(SignalType::Boolean),
            "string" | "str" => Some(SignalType::String),
            "list" | "array" => Some(SignalType::List),
            _ => None,
        }
    }
}
