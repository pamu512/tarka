# Mobile SDKs Project (Android + iOS)

## Scope

Mobile device signals, attestation collection, tamper detection, and secure request posture.

## Current Gaps

- **Shipped:** first-party **`packages/tarka-android`** and **`packages/tarka-ios`** Decision API clients with `device_context` collection — see [Android SDK](../sdks/android.md) / [iOS SDK](../sdks/ios.md).
- Attestation: apps integrate **Play Integrity** / **App Attest** and attach `Attestation` tokens; SDK provides types and challenge (`/v1/attestation/challenge`).
- MitM/tamper/replay instrumentation still benefits from broader production scenarios and optional certificate pinning in high-threat deployments.

## Roadmap

### Now

- Standardize mobile signal output to align with inference normalization.
- Improve request integrity metadata for replay/tamper analysis.

### Next

- Add stronger MitM and payload integrity instrumentation and diagnostics.
- Align attestation status taxonomy across Android/iOS.

### Later

- Cross-device trust primitives for co-location and account-defense workflows.
