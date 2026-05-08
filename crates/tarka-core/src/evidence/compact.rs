//! Compact, heap-friendly views that prefer [`Box<str>`] and borrowed data over [`String`].
//!
//! Protobuf codegen stores variable-length UTF-8 in [`String`] fields; these types mirror the same
//! logical shape for application code that wants cheaper cloning for immutable identifiers.

use serde::{Deserialize, Serialize};
use std::borrow::Cow;
use uuid::Uuid;

use super::{
    CryptoSignature, EvidenceManifest, Header, InputMap, Metadata, SignalValue, Step, Trace,
};

/// Header fields using [`Box<str>`] for immutable UTF-8 blobs (engine revision, etc.).
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct HeaderCompact {
    pub manifest_id: [u8; 16],
    pub engine_version: Box<str>,
    pub timestamp_ns: u64,
    pub engine_fingerprint: Box<str>,
}

/// One evaluation step with compact string storage.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct StepCompact {
    pub rule_id: Box<str>,
    pub logic_operator: Box<str>,
    pub operands: Vec<Box<str>>,
    pub result: bool,
    /// Intermediate variables; values use [`Cow`] to allow zero-copy deserialization from JSON.
    pub state_snapshot: std::collections::BTreeMap<Box<str>, Cow<'static, str>>,
    /// OpenTelemetry W3C trace id (32 hex chars); empty when absent.
    pub otel_trace_id: Box<str>,
}

/// Trace using compact steps.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct TraceCompact {
    pub steps: Vec<StepCompact>,
}

/// Cryptographic envelope using [`Box<str>`] for algorithm labels and key identifiers.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct CryptoSignatureCompact {
    pub algorithm: Box<str>,
    pub signature: Vec<u8>,
    pub key_id: Box<str>,
}

/// Full manifest mirroring [`EvidenceManifest`] with compact string strategy on hot paths.
///
/// [`PartialEq`] is supported but [`Eq`] is not: [`InputMap`] may carry floating-point signals.
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct EvidenceManifestCompact {
    pub header: Option<HeaderCompact>,
    pub input_map: Option<InputMap>,
    pub trace: Option<TraceCompact>,
    pub metadata: Option<Metadata>,
    pub crypto_signature: Option<CryptoSignatureCompact>,
}

impl TryFrom<Header> for HeaderCompact {
    type Error = uuid::Error;

    fn try_from(value: Header) -> Result<Self, Self::Error> {
        let uuid = Uuid::from_slice(value.manifest_id.as_slice())?;
        Ok(HeaderCompact {
            manifest_id: *uuid.as_bytes(),
            engine_version: value.engine_version.into_boxed_str(),
            timestamp_ns: value.timestamp_ns,
            engine_fingerprint: value.engine_fingerprint.into_boxed_str(),
        })
    }
}

impl From<HeaderCompact> for Header {
    fn from(value: HeaderCompact) -> Self {
        Header {
            manifest_id: value.manifest_id.to_vec(),
            engine_version: value.engine_version.into(),
            timestamp_ns: value.timestamp_ns,
            engine_fingerprint: value.engine_fingerprint.into(),
        }
    }
}

impl From<Step> for StepCompact {
    fn from(value: Step) -> Self {
        StepCompact {
            rule_id: value.rule_id.into_boxed_str(),
            logic_operator: value.logic_operator.into_boxed_str(),
            operands: value
                .operands
                .into_iter()
                .map(|operand| operand.into_boxed_str())
                .collect(),
            result: value.result,
            state_snapshot: value
                .state_snapshot
                .into_iter()
                .map(|(key, value)| (key.into_boxed_str(), Cow::Owned(value)))
                .collect(),
            otel_trace_id: value.otel_trace_id.into_boxed_str(),
        }
    }
}

impl From<StepCompact> for Step {
    fn from(value: StepCompact) -> Self {
        Step {
            rule_id: value.rule_id.into(),
            logic_operator: value.logic_operator.into(),
            operands: value.operands.into_iter().map(|operand| operand.into()).collect(),
            result: value.result,
            state_snapshot: value
                .state_snapshot
                .into_iter()
                .map(|(key, value)| (key.into(), value.into_owned()))
                .collect(),
            otel_trace_id: value.otel_trace_id.into(),
        }
    }
}

impl From<Trace> for TraceCompact {
    fn from(value: Trace) -> Self {
        TraceCompact {
            steps: value.steps.into_iter().map(StepCompact::from).collect(),
        }
    }
}

impl From<TraceCompact> for Trace {
    fn from(value: TraceCompact) -> Self {
        Trace {
            steps: value.steps.into_iter().map(Step::from).collect(),
        }
    }
}

impl From<CryptoSignature> for CryptoSignatureCompact {
    fn from(value: CryptoSignature) -> Self {
        CryptoSignatureCompact {
            algorithm: value.algorithm.into_boxed_str(),
            signature: value.signature,
            key_id: value.key_id.into_boxed_str(),
        }
    }
}

impl From<CryptoSignatureCompact> for CryptoSignature {
    fn from(value: CryptoSignatureCompact) -> Self {
        CryptoSignature {
            algorithm: value.algorithm.into(),
            signature: value.signature,
            key_id: value.key_id.into(),
        }
    }
}

impl TryFrom<EvidenceManifest> for EvidenceManifestCompact {
    type Error = uuid::Error;

    fn try_from(value: EvidenceManifest) -> Result<Self, Self::Error> {
        Ok(EvidenceManifestCompact {
            header: value
                .header
                .map(HeaderCompact::try_from)
                .transpose()?,
            input_map: value.input_map,
            trace: value.trace.map(TraceCompact::from),
            metadata: value.metadata,
            crypto_signature: value.crypto_signature.map(CryptoSignatureCompact::from),
        })
    }
}

impl From<EvidenceManifestCompact> for EvidenceManifest {
    fn from(value: EvidenceManifestCompact) -> Self {
        EvidenceManifest {
            header: value.header.map(Into::into),
            input_map: value.input_map,
            trace: value.trace.map(Into::into),
            metadata: value.metadata,
            crypto_signature: value.crypto_signature.map(Into::into),
        }
    }
}

impl SignalValue {
    /// Returns a compact [`Cow<str>`] when this signal holds UTF-8 text without allocating.
    pub fn string_as_cow(&self) -> Option<Cow<'_, str>> {
        match &self.value {
            Some(super::signal_value::Value::StringValue(ref owned)) => {
                Some(Cow::Borrowed(owned.as_str()))
            }
            _ => None,
        }
    }
}
