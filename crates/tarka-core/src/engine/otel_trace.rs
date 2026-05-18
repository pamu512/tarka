//! OpenTelemetry **trace id** propagation (W3C: 128-bit identifier as 32 hexadecimal characters).

use thiserror::Error;
use uuid::Uuid;

/// Invalid caller-supplied trace id (does not match W3C hex layout).
#[derive(Debug, Error)]
pub enum OtelTraceIdError {
    #[error(
        "OpenTelemetry trace id must be exactly 32 hexadecimal characters (W3C); got length {len}"
    )]
    InvalidLength { len: usize },
    #[error("OpenTelemetry trace id must contain only hexadecimal digits")]
    InvalidHex,
}

/// Invalid caller-supplied span id (does not match W3C hex layout).
#[derive(Debug, Error)]
pub enum OtelSpanIdError {
    #[error(
        "OpenTelemetry span id must be exactly 16 hexadecimal characters (W3C); got length {len}"
    )]
    InvalidLength { len: usize },
    #[error("OpenTelemetry span id must contain only hexadecimal digits")]
    InvalidHex,
}

/// Normalizes a W3C trace id: trims ASCII whitespace, requires exactly 32 hex digits, returns lowercase hex.
///
/// Returns [`None`] when `input` is [`None`] or empty after trim (caller may substitute a fresh random id).
pub fn normalize_otel_trace_id(input: Option<&str>) -> Result<Option<String>, OtelTraceIdError> {
    let Some(raw) = input else {
        return Ok(None);
    };
    let t = raw.trim();
    if t.is_empty() {
        return Ok(None);
    }
    if t.len() != 32 {
        return Err(OtelTraceIdError::InvalidLength { len: t.len() });
    }
    if !t.chars().all(|c| c.is_ascii_hexdigit()) {
        return Err(OtelTraceIdError::InvalidHex);
    }
    Ok(Some(t.to_ascii_lowercase()))
}

/// Random 128-bit trace id encoded as 32 lowercase hex characters (W3C layout).
pub fn random_w3c_trace_id() -> String {
    hex::encode(*Uuid::new_v4().as_bytes())
}

/// Normalizes a W3C span id: trims ASCII whitespace, requires exactly 16 hex digits, returns lowercase hex.
///
/// Returns [`None`] when `input` is [`None`] or empty after trim.
pub fn normalize_otel_span_id(input: Option<&str>) -> Result<Option<String>, OtelSpanIdError> {
    let Some(raw) = input else {
        return Ok(None);
    };
    let t = raw.trim();
    if t.is_empty() {
        return Ok(None);
    }
    if t.len() != 16 {
        return Err(OtelSpanIdError::InvalidLength { len: t.len() });
    }
    if !t.chars().all(|c| c.is_ascii_hexdigit()) {
        return Err(OtelSpanIdError::InvalidHex);
    }
    Ok(Some(t.to_ascii_lowercase()))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn normalizes_lower_case() {
        let u = "A".repeat(32);
        let out = normalize_otel_trace_id(Some(&u)).expect("ok");
        assert_eq!(out, Some("a".repeat(32)));
    }

    #[test]
    fn rejects_short_id() {
        let err = normalize_otel_trace_id(Some("abc")).expect_err("short");
        assert!(matches!(err, OtelTraceIdError::InvalidLength { .. }));
    }

    #[test]
    fn rejects_non_hex() {
        let s = "g".to_string().repeat(32);
        let err = normalize_otel_trace_id(Some(&s)).expect_err("non-hex");
        assert!(matches!(err, OtelTraceIdError::InvalidHex));
    }

    #[test]
    fn span_id_normalizes_lower_case() {
        let u = "A".repeat(16);
        let out = normalize_otel_span_id(Some(&u)).expect("ok");
        assert_eq!(out, Some("a".repeat(16)));
    }

    #[test]
    fn span_id_rejects_wrong_length() {
        let err = normalize_otel_span_id(Some("abc")).expect_err("short");
        assert!(matches!(err, OtelSpanIdError::InvalidLength { .. }));
    }
}
