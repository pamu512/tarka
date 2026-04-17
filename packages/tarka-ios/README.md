# Tarka iOS SDK (Swift Package)

Apache-2.0. **Swift Package** for the Tarka **Decision API** with **`device_context`** aligned to [`contracts/json-schema/device-context.json`](../../contracts/json-schema/device-context.json).

## Requirements

- iOS **15+**, Swift **5.9+**

## Add to Xcode

**File → Add Package Dependencies →** add local path `packages/tarka-ios` or the Git URL once published.

## Usage

```swift
import TarkaSDK

let client = DecisionClient(baseUrl: "https://your-decision-api:8000", apiKey: "your-key")
let response = try await client.evaluate(EvaluateRequest(
    tenant_id: "acme",
    event_type: "login",
    entity_id: "user-123",
    payload: ["amount": .double(49.99)]
))
print(response.decision, response.score)
```

### App Attest (optional)

1. `let nonce = try await client.requestChallenge(tenantId: "acme")`
2. Use `DeviceCheck` / `App Attest` to produce an assertion bound to `nonce`.
3. Set `device_context.attestation = Attestation(nonce: nonce, token: "<assertion>", provider: "app_attest")` on the request (build `DeviceContext` manually).

## Tests

```bash
cd packages/tarka-ios && swift test
```
