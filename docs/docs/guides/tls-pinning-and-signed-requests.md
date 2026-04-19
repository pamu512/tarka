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

Canonical helpers: **`services/shared/tarka_request_signature.py`** and **`packages/fraud-sdk-python`** (`fraud_stack_sdk.request_signing`).

- **Server (decision-api):** set **`REQUEST_SIGNATURE_SECRET`** to enable optional verification on **`POST /v1/decisions/evaluate`** (same HMAC). When unset, evaluate is unchanged (many teams still terminate signing at **Envoy / Kong / Cloudflare**).
- **Client:** compute HMAC in the app and add headers; **never** embed the secret in the client for public apps — use **per-install** keys from your backend or mTLS instead.

Edge gateways with **mTLS** to decision-api remain a common pattern for multi-hop setups.

## Related

- `services/decision-api` — `metadata.tls_pinning_verified` in evaluate path  
- [SDK scorecard](./sdk-scorecard-2026-01.md)  
- [Regulated markets feature pack](./feature-pack-regulated-markets.md) — optional checklist for fintech / banking / crypto-style deployments
