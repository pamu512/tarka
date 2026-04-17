# fraud-sdk-android (Kotlin)

Apache-2.0. **`io.tarka.sdk`** — Decision API client with **`device_context`**, optional **Play Integrity** (`com.google.android.play:integrity`), OkHttp.

## Module layout

- **Gradle:** `settings.gradle.kts` includes `:fraud-sdk` (library under `fraud-sdk/`).

```kotlin
// settings.gradle.kts in your app
include(":fraud-sdk")
project(":fraud-sdk").projectDir = file("../packages/fraud-sdk-android/fraud-sdk")
```

```kotlin
dependencies {
    implementation(project(":fraud-sdk"))
}
```

## Usage

```kotlin
val client = DecisionClient(
    baseUrl = "https://your-api:8000",
    apiKey = "key",
    context = applicationContext,
    enablePlayIntegrity = true,
)
val res = client.evaluate(
    EvaluateRequest(
        tenantId = "acme",
        eventType = "login",
        entityId = "user-1",
        payload = mapOf("ip" to "203.0.113.1"),
        metadata = mapOf("vendor_visitor_id" to "fp_abc"), // optional bridge
    ),
)
```

## Semantics

See [device-id semantics](../../docs/docs/guides/device-id-semantics.md) and [TLS pinning](../../docs/docs/guides/tls-pinning-and-signed-requests.md).
