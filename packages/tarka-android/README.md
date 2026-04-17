# Tarka Android SDK (Kotlin)

Apache-2.0. Minimal **Decision API** client with **`device_context`** aligned to [`contracts/json-schema/device-context.json`](../../contracts/json-schema/device-context.json) and the TypeScript SDK.

## Requirements

- Android **minSdk 24**, Kotlin **2.0+**, **OkHttp 4**

## Gradle (include as composite or copy module)

From repo root:

```kotlin
// settings.gradle.kts
include(":tarka-sdk")
project(":tarka-sdk").projectDir = file("packages/tarka-android/tarka-sdk")
```

```kotlin
dependencies {
    implementation(project(":tarka-sdk"))
}
```

Or publish the `tarka-sdk` module to Maven Local and depend on `io.tarka:tarka-sdk`.

## Usage

```kotlin
val client = DecisionClient(
    baseUrl = "https://your-decision-api:8000",
    apiKey = "your-key",
    context = applicationContext,
)
val res = client.evaluate(
    EvaluateRequest(
        tenantId = "acme",
        eventType = "login",
        entityId = "user-123",
        payload = mapOf("ip" to "203.0.113.1"),
    ),
)
println(res.decision + " " + res.score)
```

### Play Integrity (optional)

1. Add Google Play Integrity dependency in your app.
2. `val nonce = client.requestChallenge("acme")`
3. Obtain a token from Play Integrity with that nonce.
4. Build `DeviceContext` with `Attestation(nonce, token, "play_integrity")` and pass on `EvaluateRequest`.

## Tests

```bash
./gradlew :tarka-sdk:test
```
