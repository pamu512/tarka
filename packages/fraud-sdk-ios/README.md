# fraud-sdk-ios (Swift Package)

Apache-2.0. **`TarkaSDK`** — `DecisionClient` + **`DeviceSignalCollector`** + optional **App Attest** (`DCAppAttestService`).

Add local path `packages/fraud-sdk-ios` in Xcode SPM.

```swift
import TarkaSDK

let client = DecisionClient(baseURL: "https://your-api:8000", apiKey: "key", enableAppAttest: true)
let res = try await client.evaluate(tenantId: "acme", eventType: "login", entityId: "u1")
```

## Semantics

See [device-id semantics](../../docs/docs/guides/device-id-semantics.md), [mobile attestation taxonomy](../../docs/docs/guides/mobile-attestation-taxonomy.md), and [TLS pinning](../../docs/docs/guides/tls-pinning-and-signed-requests.md).

When App Attest is enabled, the SDK always sends an **`attestation`** object: **`obtained`**, **`failed`**, **`unsupported`**, or **`disabled`** (with **`confidence_tier`** and **`attestation_schema_version`**).
