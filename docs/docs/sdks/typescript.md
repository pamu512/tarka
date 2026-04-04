# TypeScript SDK

The TypeScript SDK (`@tarka/sdk`) provides a browser-side client for the Decision API with automatic device signal collection, fingerprinting, and attestation. Use it in your web application to evaluate fraud decisions with rich client-side context.

**Package:** `@tarka/sdk`
**Runtime:** Browser (uses `crypto.subtle`, `navigator`, `RTCPeerConnection`)
**Dependencies:** None (zero dependencies, uses native `fetch`)

---

## Installation

```bash
npm install @tarka/sdk
```

Or install from source:

```bash
cd packages/fraud-sdk-typescript
npm install
npm run build
```

---

## Basic Usage

```typescript
import { DecisionClient } from "@tarka/sdk";

const client = new DecisionClient({
  baseUrl: "http://localhost:8000",
  apiKey: "your-api-key",
  autoCollectSignals: true,
});

const result = await client.evaluate({
  tenant_id: "acme",
  event_type: "payment",
  entity_id: "user-42",
  payload: {
    amount: 499.99,
    currency: "USD",
  },
});

console.log(result.decision);  // "allow" | "review" | "deny"
console.log(result.score);     // 0–100
console.log(result.trace_id);  // UUID
```

### Event ingest (async NATS path)

Use **`EventIngestClient`** against the event-ingest service (e.g. port **8007** in full Docker Compose). Pass an optional second argument for **`Idempotency-Key`** when ingest has **`REDIS_URL`** configured.

```typescript
import { EventIngestClient } from "@tarka/sdk";

const ingest = new EventIngestClient({
  baseUrl: "http://localhost:8007",
  apiKey: "your-api-key",
});

const ack = await ingest.sendEvent(
  {
    tenant_id: "acme",
    event_type: "login",
    entity_id: "user-42",
    payload: { ip: "203.0.113.10" },
  },
  "optional-client-request-id"
);
console.log(ack.ingest_id);
```

See **[Ingest, idempotency & replay](../guides/ingest-replay-onboarding.md)**.

When `autoCollectSignals` is `true` (the default), the SDK automatically:

1. Collects device signals (emulator, VPN, bot, headless, automation detection)
2. Generates a stable device fingerprint from canvas, WebGL, screen, and language
3. Performs a browser attestation challenge (HMAC-based)
4. Attaches everything as `device_context` on the evaluate request

---

## Signal Collection

The SDK collects the following device signals:

| Signal | Detection Method |
|---|---|
| `is_emulator` | Headless + WebDriver combined |
| `is_vpn` | WebRTC IP leak detection (STUN) |
| `is_bot` | No mouse/keyboard/touch interaction detected |
| `is_repackaged` | Reserved for mobile SDKs |
| `is_spoofed_location` | Reserved for mobile SDKs |
| `webdriver_detected` | `navigator.webdriver`, `__nightmare`, `domAutomation` |
| `headless_detected` | HeadlessChrome UA, missing plugins, empty languages |
| `automation_detected` | Selenium, PhantomJS, Puppeteer markers |
| `vpn_interface_detected` | WebRTC private IP leak |
| `mock_location_detected` | Reserved for mobile SDKs |
| `timezone_geo_mismatch` | Reserved (implement with GeoIP) |
| `canvas_fp_hash` | Canvas fingerprint SHA-256 hash |
| `webgl_renderer` | WebGL renderer string |
| `screen_res` | Screen resolution (`widthxheight`) |
| `touch_support` | Touch input available |
| `battery_api_present` | Battery API exists |
| `language` | Browser language |
| `platform_version` | User agent string |

### Manual Signal Collection

For custom flows, use `DeviceSignalCollector` directly:

```typescript
import { DeviceSignalCollector } from "@tarka/sdk";

const collector = new DeviceSignalCollector();
const signals = await collector.collect();

console.log(signals.is_vpn);            // boolean
console.log(signals.webdriver_detected); // boolean
console.log(signals.canvas_fp_hash);     // string | null

const deviceContext = await collector.buildDeviceContext();
console.log(deviceContext.device_id);    // SHA-256 fingerprint
console.log(deviceContext.platform);     // "web"

// Clean up event listeners when done
collector.destroy();
```

---

## Attestation

The SDK automatically performs browser attestation when `autoCollectSignals` is enabled:

1. Calls `POST /v1/attestation/challenge` to get a nonce
2. Signs `HMAC-SHA256(device_id, nonce + device_id)` using the Web Crypto API
3. Attaches `{ nonce, token, provider: "browser_challenge" }` to the device context

Attestation is **best-effort** — if the challenge request fails, the evaluation proceeds without it.

### Manual Attestation

```typescript
const nonce = await client.requestChallenge("acme");
// nonce is a hex string, valid for 300 seconds
```

---

## Audit Trail

Retrieve the audit record for a decision:

```typescript
const audit = await client.getAudit("a1b2c3d4-e5f6-7890-abcd-ef1234567890");
console.log(audit.decision);
console.log(audit.score);
console.log(audit.tags);
```

---

## Integration Examples

### React

```tsx
import { useEffect, useRef } from "react";
import { DecisionClient } from "@tarka/sdk";

const fraudClient = new DecisionClient({
  baseUrl: import.meta.env.VITE_FRAUD_API_URL,
  apiKey: import.meta.env.VITE_FRAUD_API_KEY,
});

function CheckoutButton({ userId, amount, currency }: Props) {
  const handleCheckout = async () => {
    const result = await fraudClient.evaluate({
      tenant_id: "acme",
      event_type: "payment",
      entity_id: userId,
      payload: { amount, currency },
    });

    if (result.decision === "deny") {
      alert("Transaction could not be processed.");
      return;
    }

    // Proceed with payment, include trace_id for server correlation
    await fetch("/api/checkout", {
      method: "POST",
      body: JSON.stringify({
        amount,
        currency,
        fraud_trace_id: result.trace_id,
      }),
    });
  };

  return <button onClick={handleCheckout}>Pay ${amount}</button>;
}
```

### Next.js Middleware

```typescript
import { DecisionClient } from "@tarka/sdk";

const client = new DecisionClient({
  baseUrl: process.env.FRAUD_API_URL!,
  apiKey: process.env.FRAUD_API_KEY,
  autoCollectSignals: false, // server-side, no browser APIs
});

export async function middleware(request: NextRequest) {
  const ip = request.ip || request.headers.get("x-forwarded-for") || "";
  const ua = request.headers.get("user-agent") || "";

  const result = await client.evaluate({
    tenant_id: "acme",
    event_type: "session",
    entity_id: request.cookies.get("user_id")?.value || "anonymous",
    metadata: { ip, user_agent: ua },
  });

  if (result.decision === "deny") {
    return new NextResponse("Blocked", { status: 403 });
  }

  const response = NextResponse.next();
  response.headers.set("X-Fraud-Score", String(result.score));
  response.headers.set("X-Fraud-Trace", result.trace_id);
  return response;
}
```

### Vanilla JavaScript

```html
<script type="module">
  import { DecisionClient } from "@tarka/sdk";

  const client = new DecisionClient({
    baseUrl: "http://localhost:8000",
  });

  document.getElementById("login-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const email = document.getElementById("email").value;

    const result = await client.evaluate({
      tenant_id: "acme",
      event_type: "login",
      entity_id: email,
      payload: { email },
    });

    if (result.decision === "deny") {
      document.getElementById("error").textContent = "Access denied.";
      return;
    }

    // proceed with login
    e.target.submit();
  });
</script>
```

---

## Lifecycle

The SDK attaches event listeners to `window` for behavioral analysis (mouse movements, key presses, touch events). Call `destroy()` when the client is no longer needed to clean up:

```typescript
const client = new DecisionClient({ baseUrl: "..." });

// ... use the client ...

client.destroy(); // removes event listeners
```

In React, use `useEffect` cleanup:

```tsx
useEffect(() => {
  const client = new DecisionClient({ baseUrl: "..." });
  // store in ref or context
  return () => client.destroy();
}, []);
```

---

## API Reference

### `DecisionClient`

```typescript
new DecisionClient(opts: DecisionClientOptions)
```

| Option | Type | Default | Description |
|---|---|---|---|
| `baseUrl` | string | required | Decision API base URL |
| `apiKey` | string | `""` | API key for `X-API-Key` header |
| `timeoutMs` | number | `10000` | Request timeout in milliseconds |
| `autoCollectSignals` | boolean | `true` | Auto-collect device signals |

#### Methods

| Method | Returns | Description |
|---|---|---|
| `evaluate(body: EvaluateRequest)` | `Promise<EvaluateResponse>` | Evaluate a fraud decision |
| `requestChallenge(tenantId: string)` | `Promise<string>` | Request attestation nonce |
| `getAudit(traceId: string)` | `Promise<Record<string, unknown>>` | Get audit record |
| `destroy()` | `void` | Clean up event listeners |

### `DeviceSignalCollector`

```typescript
new DeviceSignalCollector()
```

#### Methods

| Method | Returns | Description |
|---|---|---|
| `collect()` | `Promise<DeviceSignals>` | Collect all device signals |
| `buildDeviceContext()` | `Promise<DeviceContext>` | Build complete device context with fingerprint |
| `destroy()` | `void` | Clean up event listeners |

### Types

```typescript
type EventType = "login" | "payment" | "signup" | "device" | "session" | "custom";

interface EvaluateRequest {
  tenant_id: string;
  event_type: EventType;
  entity_id: string;
  session_id?: string | null;
  payload?: Record<string, unknown>;
  device_context?: DeviceContext | null;
  metadata?: Record<string, unknown>;
}

interface EvaluateResponse {
  trace_id: string;
  decision: string;
  score: number;
  tags: string[];
  rule_hits?: string[];
  reasons?: string[];
  ml_score?: number | null;
}

interface DeviceContext {
  device_id: string;
  platform: "web" | "android" | "ios" | "server";
  signals: DeviceSignals;
  attestation?: Attestation | null;
}
```
