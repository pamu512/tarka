//! Structured compiler failures (YAML parse, schema, unknown signals).

use std::fmt;

/// Failure produced while compiling YAML into a protobuf [`RuleSet`](crate::compiler::RuleSet).
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct CompileError {
    /// Human-readable explanation (stable for logs; no internal panics).
    pub message: String,
    /// Best-effort 1-based source line (YAML layout-dependent).
    pub line: Option<u32>,
    /// Closest matching registry entry when a signal name is invalid.
    pub suggestion: Option<String>,
}

impl fmt::Display for CompileError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{}", self.message)?;
        if let Some(l) = self.line {
            write!(f, " (line {l})")?;
        }
        if let Some(s) = &self.suggestion {
            write!(f, "; did you mean `{s}`?")?;
        }
        Ok(())
    }
}

impl std::error::Error for CompileError {}

impl CompileError {
    pub(crate) fn yaml_parse(message: impl Into<String>, line: Option<u32>) -> Self {
        Self {
            message: message.into(),
            line,
            suggestion: None,
        }
    }

    pub(crate) fn undefined_signal(
        signal: impl Into<String>,
        line: Option<u32>,
        suggestion: Option<String>,
    ) -> Self {
        let signal = signal.into();
        Self {
            message: format!("undefined signal `{signal}` (not present in SignalRegistry)"),
            line,
            suggestion,
        }
    }

    pub(crate) fn validation(message: impl Into<String>, line: Option<u32>) -> Self {
        Self {
            message: message.into(),
            line,
            suggestion: None,
        }
    }
}
