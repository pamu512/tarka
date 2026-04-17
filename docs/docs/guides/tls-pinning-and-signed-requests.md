# TLS pinning and signed requests (high-threat mobile / web)

Tarka’s HTTP SDKs use **system TLS** (URLSession / OkHttp) by default. For regulated or high-fraud environments, add **certificate pinning** and optionally **signed request bodies** so MitM proxies cannot silently rewrite JSON.

## TLS pinning patterns

### Android (OkHttp `CertificatePinner`)

1. Obtain SPKI hashes of your API leaf/intermediate certs (pin **backup** pins for rotation).
2. Build a `CertificatePinner` and attach to the `OkHttpClient` used by your fork of `DecisionClient` (or subclass).

```kotlin
val pinner = CertificatePinner.Builder()
    .add("api.example.com", "sha256/AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=")
    .build()
val client = OkHttpClient.Builder()
    .certificatePinner(pinner)
    .build()
```

3. Set **`metadata.tls_pinning_verified: true`** on evaluate requests **only** after a successful pin-verified connection (Decision API reads this for integrity hints — see `integrity_policy.py`).

### iOS (URLSession delegate)

Use `URLSessionDelegate` with `urlSession(_:didReceive:completionHandler:)` and `SecTrust` + pinned SPKI or public key. Wire the session into a custom `DecisionClient` if you fork the SDK.

### Web

Prefer **HTTPS** + **CORS**-correct API; pinning in browsers is limited. Use **Subresource Integrity** for static assets; for API calls, rely on **SameSite cookies** + **short-lived tokens** and server-side attestation.

## Optional signed request helper

**Pattern:** `X-Tarka-Timestamp` + `X-Tarka-Signature` = HMAC-SHA256 over `timestamp + "\n" + raw_body` with a **shared secret** rotated per tenant.

- **Server:** validate in middleware before JSON parse (not shipped in core decision-api by default — implement in API gateway or Envoy).
- **Client:** compute HMAC in the app and add headers; **never** embed the secret in the client for public apps — use **per-install** keys from your backend or mTLS instead.

For OSS Tarka, **document** this pattern; production teams often place signing at **Envoy / Kong / Cloudflare** with **mTLS** between gateway and decision-api.

## Related

- `services/decision-api` — `metadata.tls_pinning_verified` in evaluate path  
- [SDK scorecard](./sdk-scorecard-2026-01.md)
