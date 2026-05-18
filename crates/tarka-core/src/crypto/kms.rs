//! AWS KMS-backed signing (`ECC_NIST_EDWARDS25519`). Private key material never enters process memory.

use std::time::Duration;

use aws_config::BehaviorVersion;
use aws_sdk_kms::{
    error::SdkError,
    operation::sign::SignError,
    primitives::Blob,
    types::{MessageType, SigningAlgorithmSpec},
};
use ed25519_dalek::Signature;
use tokio::time::sleep;

use crate::crypto::{KmsConnectionError, Signer, SigningError};

/// KMS asymmetric signing client for Merkle roots using **Ed25519ph** (`ED25519_PH_SHA_512`, raw message).
///
/// The Merkle root (32 bytes) is sent as the KMS **RAW** message; KMS SHA-512 prehashes per AWS rules.
/// Verification uses [`ed25519_dalek::VerifyingKey::verify_prehashed`] with SHA-512 over the same root.
#[derive(Clone)]
pub struct KmsSigner {
    client: aws_sdk_kms::Client,
    key_id: String,
}

impl KmsSigner {
    /// Build from an existing SDK config (credentials + region from env/instance profile, etc.).
    pub fn new(config: &aws_config::SdkConfig, key_id: impl Into<String>) -> Self {
        Self {
            client: aws_sdk_kms::Client::new(config),
            key_id: key_id.into(),
        }
    }

    /// Loads AWS configuration via [`aws_config::defaults`] and constructs a signer for `key_id`.
    pub async fn from_default_config(key_id: impl Into<String>) -> Self {
        let cfg = aws_config::defaults(BehaviorVersion::latest()).load().await;
        Self::new(&cfg, key_id)
    }

    /// Reads `TARKA_KMS_KEY_ID`, falling back to `AWS_KMS_KEY_ID`, then loads config from the environment.
    pub async fn from_env() -> Result<Self, KmsConnectionError> {
        let key_id = std::env::var("TARKA_KMS_KEY_ID")
            .or_else(|_| std::env::var("AWS_KMS_KEY_ID"))
            .map_err(|_| KmsConnectionError::MissingKeyId)?;
        Ok(Self::from_default_config(key_id).await)
    }

    async fn sign_once(&self, root: &[u8; 32]) -> Result<Signature, SigningError> {
        let out = self
            .client
            .sign()
            .key_id(&self.key_id)
            .message(Blob::new(root.to_vec()))
            .message_type(MessageType::Raw)
            .signing_algorithm(SigningAlgorithmSpec::Ed25519PhSha512)
            .send()
            .await
            .map_err(map_sign_sdk_error)?;

        let blob = out.signature().ok_or_else(|| {
            SigningError::Kms(KmsConnectionError::UnexpectedResponse(
                "SignOutput.signature missing".into(),
            ))
        })?;

        let raw = blob.as_ref();
        Signature::from_slice(raw).map_err(|_| SigningError::InvalidSignatureLength {
            expected: ed25519_dalek::SIGNATURE_LENGTH,
            actual: raw.len(),
        })
    }

    async fn sign_with_throttle_retries(&self, root: &[u8; 32]) -> Result<Signature, SigningError> {
        const MAX_ATTEMPTS: u32 = 8;
        let mut delay = Duration::from_millis(50);

        for attempt in 1..=MAX_ATTEMPTS {
            match self.sign_once(root).await {
                Ok(sig) => return Ok(sig),
                Err(e) if should_retry(&e) && attempt < MAX_ATTEMPTS => {
                    sleep(delay).await;
                    let next_ms = (delay.as_millis() as u64).saturating_mul(2).min(10_000);
                    delay = Duration::from_millis(next_ms.max(10));
                }
                Err(e) if should_retry(&e) => {
                    return Err(SigningError::ThrottlingExhausted {
                        attempts: MAX_ATTEMPTS,
                    });
                }
                Err(e) => return Err(e),
            }
        }

        Err(SigningError::ThrottlingExhausted {
            attempts: MAX_ATTEMPTS,
        })
    }
}

impl Signer for KmsSigner {
    #[allow(clippy::manual_async_fn)]
    fn sign_merkle_root<'a>(
        &'a self,
        root: &'a [u8; 32],
    ) -> impl std::future::Future<Output = Result<Signature, SigningError>> + Send + 'a {
        async move { self.sign_with_throttle_retries(root).await }
    }
}

fn should_retry(err: &SigningError) -> bool {
    matches!(
        err,
        SigningError::Kms(KmsConnectionError::SdkRetryable { .. })
            | SigningError::Kms(KmsConnectionError::Throttling { .. })
    )
}

fn map_sign_sdk_error(err: SdkError<SignError>) -> SigningError {
    match err {
        SdkError::DispatchFailure(e) => {
            SigningError::Kms(KmsConnectionError::Dispatch(format!("{e:?}")))
        }
        SdkError::TimeoutError(_) => SigningError::Kms(KmsConnectionError::Timeout),
        SdkError::ResponseError(r) => SigningError::Kms(KmsConnectionError::Http(format!(
            "{r:?}"
        ))),
        SdkError::ServiceError(se) => map_service_sign_error(se.err()),
        SdkError::ConstructionFailure(e) => SigningError::Kms(KmsConnectionError::Unexpected(
            format!("{e:?}"),
        )),
        _ => SigningError::Kms(KmsConnectionError::Unexpected(err.to_string())),
    }
}

fn map_service_sign_error(err: &SignError) -> SigningError {
    let code = err.meta().code().unwrap_or("").to_string();
    let msg = err.meta().message().unwrap_or("").to_string();

    if matches!(
        code.as_str(),
        "ThrottlingException" | "TooManyRequestsException" | "RequestLimitExceeded"
    ) {
        return SigningError::Kms(KmsConnectionError::Throttling { code, msg });
    }

    match err {
        SignError::KmsInternalException(_)
        | SignError::DependencyTimeoutException(_)
        | SignError::KeyUnavailableException(_) => SigningError::Kms(KmsConnectionError::SdkRetryable {
            code,
            msg,
        }),
        _ => SigningError::Kms(KmsConnectionError::Service { code, msg }),
    }
}
