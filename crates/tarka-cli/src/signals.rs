//! Reconstruct evaluation JSON from ClickHouse `signals` map (inverse of ingestor stringification).

use serde_json::{json, Value};

/// Decode values captured on the wire as strings (matches ingestor `_signal_value_to_str` semantics loosely).
pub fn normalize_signal_value(v: &Value) -> Value {
    match v {
        Value::String(s) => decode_signal_string(s),
        other => other.clone(),
    }
}

fn decode_signal_string(s: &str) -> Value {
    if s == "true" {
        return json!(true);
    }
    if s == "false" {
        return json!(false);
    }
    if let Ok(v) = serde_json::from_str::<Value>(s) {
        return v;
    }
    if let Ok(i) = s.parse::<i64>() {
        return json!(i);
    }
    if let Ok(f) = s.parse::<f64>() {
        return json!(f);
    }
    Value::String(s.to_string())
}

/// Build the JSON document passed to [`tarka_core::engine::Evaluator::evaluate`], stripping forensic metadata keys.
pub fn evaluation_payload(signals: &serde_json::Map<String, Value>) -> Value {
    let mut out = serde_json::Map::new();
    for (k, v) in signals {
        if k.starts_with("tarka.") {
            continue;
        }
        out.insert(k.clone(), normalize_signal_value(v));
    }
    Value::Object(out)
}

/// Extract `tarka.rule_content_id` when producers embed the lowercase hex digest.
pub fn embedded_rule_content_id(signals: &serde_json::Map<String, Value>) -> Option<String> {
    let raw = signals.get("tarka.rule_content_id")?;
    match raw {
        Value::String(s) => Some(s.trim().to_lowercase()),
        Value::Number(n) => Some(n.to_string()),
        _ => None,
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn evaluation_payload_strips_tarka_meta_keys() {
        let mut m = serde_json::Map::new();
        m.insert("tarka.rule_content_id".into(), json!("ab".repeat(32)));
        m.insert("amount".into(), json!("42"));
        let v = evaluation_payload(&m);
        assert_eq!(v["amount"], json!(42));
        assert!(v.as_object().unwrap().get("tarka.rule_content_id").is_none());
    }
}
