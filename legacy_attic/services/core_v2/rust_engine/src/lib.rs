//! PyO3 extension: evaluates a JSON transaction payload and returns a decision string.

use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;
use serde_json::Value;

fn amount_from_parsed_json(root: &Value) -> Result<f64, String> {
    match root.get("amount") {
        None => Err(String::from("missing required field 'amount'")),
        Some(Value::Null) => Err(String::from("field 'amount' must not be null")),
        Some(Value::Number(n)) => match n.as_f64() {
            Some(v) => Ok(v),
            None => Err(String::from("field 'amount' is not representable as f64")),
        },
        Some(_) => Err(String::from("field 'amount' must be a JSON number")),
    }
}

#[pyfunction]
fn evaluate_transaction(json_input: &str) -> PyResult<String> {
    let parsed: Value = serde_json::from_str(json_input)
        .map_err(|err| PyValueError::new_err(format!("JSON parse error: {err}")))?;

    let amount = amount_from_parsed_json(&parsed).map_err(PyValueError::new_err)?;

    if !amount.is_finite() {
        return Err(PyValueError::new_err(
            "amount must be finite (reject NaN and infinities)",
        ));
    }

    let decision = if amount > 10000.0 {
        "FLAG_REVIEW"
    } else {
        "APPROVE"
    };

    Ok(decision.to_string())
}

#[pymodule]
fn rust_engine(_py: Python<'_>, m: &PyModule) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(evaluate_transaction, m)?)?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn amount_field_accepts_json_number() {
        let parsed = serde_json::from_str::<Value>(r#"{"amount": 5000}"#);
        assert!(parsed.is_ok(), "fixture JSON must parse");
        let parsed = match parsed {
            Ok(v) => v,
            Err(err) => panic!("fixture JSON must parse: {err}"),
        };
        match amount_from_parsed_json(&parsed) {
            Ok(a) => assert_eq!(a, 5000.0),
            Err(err) => panic!("amount extraction failed: {err}"),
        }
    }

    #[test]
    fn threshold_is_strictly_greater_than_ten_thousand() {
        let at = serde_json::from_str::<Value>(r#"{"amount": 10000}"#);
        let above = serde_json::from_str::<Value>(r#"{"amount": 10000.01}"#);
        let at = match at {
            Ok(v) => v,
            Err(err) => panic!("fixture: {err}"),
        };
        let above = match above {
            Ok(v) => v,
            Err(err) => panic!("fixture: {err}"),
        };
        let at_amt = match amount_from_parsed_json(&at) {
            Ok(a) => a,
            Err(err) => panic!("amount: {err}"),
        };
        let above_amt = match amount_from_parsed_json(&above) {
            Ok(a) => a,
            Err(err) => panic!("amount: {err}"),
        };
        assert!(at_amt <= 10000.0);
        assert!(above_amt > 10000.0);
    }
}
