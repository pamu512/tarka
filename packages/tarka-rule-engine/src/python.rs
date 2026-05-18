//! PyO3 extension module (separate cdylib so the watcher bin does not link libpython).

use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;
use pyo3::types::{PyDict, PyDictMethods};
use serde_json::{Map, Value};

use tarka_rule_engine::{evaluate_rules_json, EvaluationResult};

/// Sentinel passed as ``velocity_1h`` to force a Rust panic (integration / chaos tests only).
pub const PANIC_TEST_VELOCITY_SENTINEL: i32 = -911911;

#[pyclass(module = "tarka_rule_engine._native", name = "EvaluationContext")]
#[derive(Clone, Debug)]
pub struct EvaluationContext {
    #[pyo3(get, set)]
    pub graph_score: f64,
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
}

#[pyclass(module = "tarka_rule_engine._native", name = "RuleEngine")]
#[derive(Clone, Debug, Default)]
pub struct RuleEngine;

#[pymethods]
impl RuleEngine {
    #[new]
    pub fn new() -> Self {
        Self
    }

    #[pyo3(signature = (graph_score, velocity_1h))]
    pub fn evaluate<'py>(
        &self,
        py: Python<'py>,
        graph_score: f64,
        velocity_1h: i32,
    ) -> PyResult<Bound<'py, PyDict>> {
        if velocity_1h == PANIC_TEST_VELOCITY_SENTINEL {
            panic!("tarka_rule_engine_mock_panic");
        }
        let out = PyDict::new(py);
        out.set_item("graph_score", graph_score)?;
        out.set_item("velocity_1h", velocity_1h)?;
        out.set_item("ok", true)?;
        Ok(out)
    }
}

#[pyfunction]
#[pyo3(signature = (rules_json, features_json))]
fn evaluate_observation_rules_json(rules_json: String, features_json: String) -> PyResult<String> {
    let rules: Vec<Value> = serde_json::from_str(&rules_json)
        .map_err(|e| PyValueError::new_err(format!("rules_json: {e}")))?;
    let features: Value = serde_json::from_str(&features_json)
        .map_err(|e| PyValueError::new_err(format!("features_json: {e}")))?;
    let fmap = features.as_object().cloned().unwrap_or_default();
    let result: EvaluationResult = evaluate_rules_json(&rules, &fmap);
    serde_json::to_string(&result).map_err(|e| PyValueError::new_err(format!("serialize: {e}")))
}

#[pymodule]
#[pyo3(name = "_native")]
fn tarka_rule_engine_native(_py: Python<'_>, m: &Bound<'_, PyModule>) -> PyResult<()> {
    pyo3::prepare_freethreaded_python();
    m.add_class::<EvaluationContext>()?;
    m.add_class::<RuleEngine>()?;
    m.add_function(wrap_pyfunction!(evaluate_observation_rules_json, m)?)?;
    Ok(())
}
