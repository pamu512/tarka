# iOS SDK (Swift)

**Package:** [`packages/fraud-sdk-ios`](../../../packages/fraud-sdk-ios) — SwiftPM **`TarkaSDK`**.

- **`DecisionClient`** — async evaluate, optional **App Attest** attestation on `device_context`
- **`DeviceSignalCollector`** — jailbreak / VPN / simulator / integrity heuristics
- **`BehaviorCollector`** *(beta)* — typing/mouse/scroll cadence with TS-SDK parity keys (`typing`, `session`, `bot_indicators`); the server's `extract_behavior_tags` consumes it unchanged. Thinner than the web SDK (no scroll-depth or multi-touch stats yet); wire `record*` from your event handlers

**README:** [`packages/fraud-sdk-ios/README.md`](../../../packages/fraud-sdk-ios/README.md)

## Semantics and ops

- [Device ID semantics](../guides/device-id-semantics.md)  
- [TLS pinning & signed requests](../guides/tls-pinning-and-signed-requests.md)

See also: [SDK scorecard](ios.md)
