# @tarka/web-sdk

Browser helper for **consent-gated** device/session signals. Serve from a **first-party CNAME**
(e.g. `metrics.customer.com`) and pass `consentGranted` from your CMP (GDPR/CCPA).

```ts
import { collectDeviceContext, publishDeviceContext } from "@tarka/web-sdk";

const ctx = collectDeviceContext({
  publishUrl: "https://metrics.customer.com/v1/sdk/device",
  apiKey: "...",
  consentGranted: true,
});
await publishDeviceContext({ publishUrl, apiKey, consentGranted: true }, ctx);
```
