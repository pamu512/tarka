//! YAML → [`RuleSet`] compilation with central signal registry validation.
//!
//! ## YAML rule pack layout
//!
//! ```yaml
//! version: 1
//! rules:
//!   - id: example_rule
//!     expression:
//!       kind: and
//!       children:
//!         - kind: compare_signal
//!           signal_name: payment.amount
//!           op: gte
//!           expected: 5000
//! ```
//!
//! Expression nodes use `kind`: `and`, `or`, `not`, or `compare_signal`. Every `signal_name` must
//! appear in the [`SignalRegistry`] JSON loaded at compile time.

include!(concat!(env!("OUT_DIR"), "/tarka.compiler.v1.rs"));

pub mod error;
pub mod locate;
pub mod registry;
pub mod signal_type;
pub mod type_check;
pub mod yaml;

pub use error::CompileError;
pub use registry::{SignalMeta, SignalRegistry};
pub use signal_type::SignalType;
pub use type_check::{type_check_expr, TypeChecker};
pub use yaml::{compile_yaml_rule_set, YamlExpr};
