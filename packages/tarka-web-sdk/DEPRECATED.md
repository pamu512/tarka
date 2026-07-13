# @tarka/web-sdk — merged into `@tarka/sdk`

Consent-gated CNAME helpers (`collectDeviceContext`, `publishDeviceContext`) now live in
[`fraud-sdk-typescript`](../fraud-sdk-typescript/) (`src/cname_consent.ts`).

This package is a **thin re-export** of `@tarka/sdk` (package dependency, not a relative `src/` path). Prefer:

```ts
import { collectDeviceContext, publishDeviceContext } from "@tarka/sdk";
```

Mobile SDKs (`fraud-sdk-android` / `fraud-sdk-ios`) remain doc-first / separate native surfaces — not part of this merge.
