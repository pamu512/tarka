# Mobile SDKs Project (Android + iOS)

## Scope

Mobile device signals, attestation collection, tamper detection, and secure request posture.

## Current Gaps

- Attestation verification and telemetry semantics need tighter parity.
- MitM/tamper/replay instrumentation requires broader production scenarios.

## Roadmap

### Now

- Standardize mobile signal output to align with inference normalization.
- Improve request integrity metadata for replay/tamper analysis.

### Next

- Add stronger MitM and payload integrity instrumentation and diagnostics.
- Align attestation status taxonomy across Android/iOS.

### Later

- Cross-device trust primitives for co-location and account-defense workflows.
