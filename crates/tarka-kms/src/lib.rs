//! AWS KMS-backed signing for [`tarka_core::crypto::Signer`].
//!
//! This crate is intentionally **outside** the root workspace so optional AWS / `rustls` 0.21
//! dependencies do not appear in the main `Cargo.lock` scanned by Dependabot.

mod signer;

pub use signer::KmsSigner;
