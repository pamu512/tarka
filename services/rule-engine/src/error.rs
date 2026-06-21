//! Structured errors for the rule engine FFI boundary (`thiserror`).

use crate::json_ast::AstMalformed;
use thiserror::Error;

/// Canonical failure type for the Rust JSON rule engine (mapped to Python in `lib.rs`).
#[derive(Debug, Error)]
pub enum TarkaEngineError {
    #[error(
        "json_parse_failed: context={context} rule_id={rule_id:?} ast_node_index={ast_node_index:?} message={message}"
    )]
    JsonParse {
        context: &'static str,
        message: String,
        rule_id: Option<String>,
        ast_node_index: Option<usize>,
    },

    #[error(
        "json_serialize_failed: context={context} rule_id={rule_id:?} ast_node_index={ast_node_index:?} message={message}"
    )]
    JsonSerialize {
        context: &'static str,
        message: String,
        rule_id: Option<String>,
        ast_node_index: Option<usize>,
    },

    #[error(
        "regex_compilation_failed: rule_id={rule_id} ast_node_index={ast_node_index:?} pattern_len={pattern_len} message={message}"
    )]
    RegexCompilation {
        rule_id: String,
        ast_node_index: Option<usize>,
        pattern_len: usize,
        message: String,
    },

    #[error(
        "ast_validation_failed: rule_id={rule_id} ast_node_index={ast_node_index:?} path={path} code={code} message={message}"
    )]
    AstValidation {
        rule_id: String,
        ast_node_index: Option<usize>,
        path: String,
        code: String,
        message: String,
    },

    #[error("engine_not_initialized: sync_packs_json must be called before evaluate_json_rules_rust")]
    EngineNotInitialized,

    #[error(
        "evaluation_budget_exceeded: rule_id={rule_id} ast_node_index={ast_node_index:?} message={message}"
    )]
    EvaluationBudget {
        rule_id: String,
        ast_node_index: Option<usize>,
        message: String,
    },

    /// Reserved for defensive checks; surfaced to Python as ``RuleEnginePanic``.
    #[allow(dead_code)]
    #[error("internal_invariant: rule_id={rule_id} ast_node_index={ast_node_index:?} message={message}")]
    InternalInvariant {
        rule_id: String,
        ast_node_index: Option<usize>,
        message: String,
    },
}

impl From<AstMalformed> for TarkaEngineError {
    fn from(m: AstMalformed) -> Self {
        TarkaEngineError::AstValidation {
            rule_id: m.rule_id.unwrap_or_default(),
            ast_node_index: m.ast_node_index,
            path: m.path,
            code: m.code,
            message: m.message,
        }
    }
}

impl TarkaEngineError {
    /// JSON envelope for Python / FastAPI (stable keys).
    pub fn to_json_value(&self) -> serde_json::Value {
        let (code, message, rule_id, ast_node_index, path) = match self {
            TarkaEngineError::JsonParse {
                context,
                message,
                rule_id,
                ast_node_index,
            } => (
                "json_parse",
                format!("{context}: {message}"),
                rule_id.as_deref(),
                *ast_node_index,
                None,
            ),
            TarkaEngineError::JsonSerialize {
                context,
                message,
                rule_id,
                ast_node_index,
            } => (
                "json_serialize",
                format!("{context}: {message}"),
                rule_id.as_deref(),
                *ast_node_index,
                None,
            ),
            TarkaEngineError::RegexCompilation {
                rule_id,
                ast_node_index,
                pattern_len,
                message,
            } => (
                "regex_compilation",
                format!("pattern_len={pattern_len}: {message}"),
                Some(rule_id.as_str()),
                *ast_node_index,
                None,
            ),
            TarkaEngineError::AstValidation {
                rule_id,
                ast_node_index,
                path,
                code,
                message,
            } => (
                "ast_validation",
                format!("{code}: {message}"),
                Some(rule_id.as_str()),
                *ast_node_index,
                Some(path.as_str()),
            ),
            TarkaEngineError::EngineNotInitialized => ("engine_not_initialized", self.to_string(), None, None, None),
            TarkaEngineError::EvaluationBudget {
                rule_id,
                ast_node_index,
                message,
            } => (
                "evaluation_budget",
                message.clone(),
                Some(rule_id.as_str()),
                *ast_node_index,
                None,
            ),
            TarkaEngineError::InternalInvariant {
                rule_id,
                ast_node_index,
                message,
            } => (
                "internal_invariant",
                message.clone(),
                Some(rule_id.as_str()),
                *ast_node_index,
                None,
            ),
        };
        serde_json::json!({
            "code": code,
            "message": message,
            "rule_id": rule_id,
            "ast_node_index": ast_node_index,
            "path": path,
        })
    }

    pub fn json_payload_string(&self) -> String {
        self.to_json_value().to_string()
    }
}

impl From<serde_json::Error> for TarkaEngineError {
    fn from(e: serde_json::Error) -> Self {
        TarkaEngineError::JsonParse {
            context: "serde_json",
            message: e.to_string(),
            rule_id: None,
            ast_node_index: None,
        }
    }
}

pub fn json_parse_err(context: &'static str, e: serde_json::Error) -> TarkaEngineError {
    TarkaEngineError::JsonParse {
        context,
        message: e.to_string(),
        rule_id: None,
        ast_node_index: None,
    }
}

pub fn json_serialize_err(context: &'static str, e: serde_json::Error) -> TarkaEngineError {
    TarkaEngineError::JsonSerialize {
        context,
        message: e.to_string(),
        rule_id: None,
        ast_node_index: None,
    }
}

