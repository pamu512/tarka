//! gRPC contracts for internal microservice communication (`SignalService`).
//!
//! Generated from `proto/internal_comms.proto` at compile time via [`tonic_prost_build`].

pub mod pb {
    tonic::include_proto!("tarka.internal.v1");
}

pub use pb::signal_service_client::SignalServiceClient;
pub use pb::signal_service_server::{SignalService, SignalServiceServer};
pub use pb::{
    PingRequest, PongResponse, ResolvedSignal, SignalResolutionRequest, SignalResolutionResponse,
};
