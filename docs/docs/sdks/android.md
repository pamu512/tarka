# Android SDK (Kotlin)

**Package:** [`packages/fraud-sdk-android`](../../../packages/fraud-sdk-android) — module **`fraud-sdk`**, namespace **`io.tarka.sdk`**.

- **`DecisionClient`** — evaluate, attestation challenge, optional **Play Integrity** → `device_context.attestation`
- **`DeviceSignalCollector`** — signals aligned with the Decision API contract
- **`BehaviorCollector`** *(beta)* — typing/mouse/scroll cadence with TS-SDK parity keys (`typing`, `session`, `bot_indicators`); the server's `extract_behavior_tags` consumes it unchanged. Thinner than the web SDK (no scroll-depth or multi-touch stats yet); wire `record*` from your event handlers

**README:** [`packages/fraud-sdk-android/README.md`](../../../packages/fraud-sdk-android/README.md)

## Semantics and ops

- [Device ID semantics](../guides/device-id-semantics.md) — server-side entity linking + optional vendor bridge  
- [TLS pinning & signed requests](../guides/tls-pinning-and-signed-requests.md)

See also: [SDK scorecard](android.md)
