//! Compile `proto/internal_comms.proto` into Rust types + `SignalService` client/server stubs.

fn main() -> Result<(), Box<dyn std::error::Error>> {
    std::env::set_var("PROTOC", protobuf_src::protoc());

    let proto_root = std::path::PathBuf::from(std::env::var("CARGO_MANIFEST_DIR")?)
        .join("../..")
        .join("proto");

    tonic_prost_build::configure()
        .build_client(true)
        .build_server(true)
        .compile_protos(&[proto_root.join("internal_comms.proto")], &[proto_root])?;

    println!("cargo:rerun-if-changed=../../proto/internal_comms.proto");
    Ok(())
}
