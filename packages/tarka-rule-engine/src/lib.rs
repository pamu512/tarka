//! PyO3 **LFFI** surface: [`EvaluationContext`] carries graph and velocity signals; [`RuleEngine::evaluate`]
//! accepts Python ``float`` / ``int`` for those fields.
//!
//! **Test-only panic sentinel:** ``velocity_1h == -911911`` triggers a deliberate ``panic!`` so Python
//! integration tests can verify panic-to-``REVIEW`` handling (see ``PANIC_TEST_VELOCITY_SENTINEL`` in Python).

use pyo3::prelude::*;
use pyo3::types::{PyDict, PyDictMethods};

/// Sentinel passed as ``velocity_1h`` to force a Rust panic (integration / chaos tests only).
pub const PANIC_TEST_VELOCITY_SENTINEL: i32 = -911911;

/// Context passed into rule evaluation (Rust + Python).
#[pyclass(module = "tarka_rule_engine._native", name = "EvaluationContext")]
#[derive(Clone, Debug)]
pub struct EvaluationContext {
    /// Aggregated graph / neighbor risk score in ``[0, 1]`` (or engine-specific scale).
    #[pyo3(get, set)]
    pub graph_score: f64,
    /// Velocity-style counter for the last hour (e.g. Redis window aggregate).
    #[pyo3(get, set)]
    pub velocity_1h: i32,
}

#[pymethods]
impl EvaluationContext {
    #[new]
    #[pyo3(signature = (graph_score=0.0, velocity_1h=0))]
    pub fn new(graph_score: f64, velocity_1h: i32) -> Self {
        Self {
            graph_score,
            velocity_1h,
        }
    }

    fn __repr__(&self) -> String {
        format!(
            "EvaluationContext(graph_score={:?}, velocity_1h={})",
            self.graph_score, self.velocity_1h
        )
    }
}

/// Minimal evaluator stub: materializes an [`EvaluationContext`] from Python arguments.
#[pyclass(module = "tarka_rule_engine._native", name = "RuleEngine")]
#[derive(Clone, Debug, Default)]
pub struct RuleEngine;

#[pymethods]
impl RuleEngine {
    #[new]
    pub fn new() -> Self {
        Self
    }

    /// Run evaluation using explicit ``graph_score`` (``float``) and ``velocity_1h`` (``int``).
    #[pyo3(signature = (graph_score, velocity_1h))]
    pub fn evaluate<'py>(
        &self,
        py: Python<'py>,
        graph_score: f64,
        velocity_1h: i32,
    ) -> PyResult<Bound<'py, PyDict>> {
        if velocity_1h == PANIC_TEST_VELOCITY_SENTINEL {
            // Deliberate panic for PyO3 panic-recovery tests (Python maps to REVIEW).
            panic!("tarka_rule_engine_mock_panic");
        }
        let ctx = EvaluationContext {
            graph_score,
            velocity_1h,
        };
        let out = PyDict::new(py);
        out.set_item("graph_score", ctx.graph_score)?;
        out.set_item("velocity_1h", ctx.velocity_1h)?;
        out.set_item("ok", true)?;
        Ok(out)
    }
}

#[pymodule]
fn _native(_py: Python<'_>, m: &Bound<'_, PyModule>) -> PyResult<()> {
    pyo3::prepare_freethreaded_python();
    m.add_class::<EvaluationContext>()?;
    m.add_class::<RuleEngine>()?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn evaluation_context_fields() {
        let c = EvaluationContext {
            graph_score: 0.25,
            velocity_1h: 7,
        };
        assert!((c.graph_score - 0.25).abs() < f64::EPSILON);
        assert_eq!(c.velocity_1h, 7);
    }
}
