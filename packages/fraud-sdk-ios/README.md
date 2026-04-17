# fraud-sdk-ios (Swift Package)

Apache-2.0. **`TarkaSDK`** — `DecisionClient` + **`DeviceSignalCollector`** + optional **App Attest** (`DCAppAttestService`).

Add local path `packages/fraud-sdk-ios` in Xcode SPM.

```swift
import TarkaSDK

let client = DecisionClient(baseURL: "https://your-api:8000", apiKey: "key", enableAppAttest: true)
let res = try await client.evaluate(tenantId: "acme", eventType: "login", entityId: "u1")
```

## Semantics

See [device-id semantics](../../docs/docs/guides/device-id-semantics.md) and [TLS pinning](../../docs/docs/guides/tls-pinning-and-signed-requests.md).
