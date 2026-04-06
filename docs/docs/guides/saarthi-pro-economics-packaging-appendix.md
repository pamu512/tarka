# Saarthi Pro — economics & packaging appendix (internal)

> **Internal clarity** for quotes. Aligns with [adapter-first pricing](saarthi-pro-adapter-strategy-and-pricing.md). Not customer-facing until finance approves.

## Components (recap)

| Component | When to use | Avoid double-counting |
|-----------|-------------|------------------------|
| **Platform** | Every deployment | Base runtime + standard support |
| **Maintained adapter** | Per `integration_profile_id` / connected stack | Don’t bundle unlimited adapter work |
| **Seats / MAU** | Analyst-heavy SKUs | Skip if procurement only buys API capacity |
| **SLA uplift** | P1/P2 targets | Reference [support severity](saarthi-pro-support-severity.md) defaults vs contracted |
| **Bundled inference** | Customer wants single invoice for LLM | Must name subprocessor + region; margin risk—price above raw token cost |

## Bundled inference SKUs (Phase 3)

- **Meter:** tokens in/out per month **or** included cap + overage.
- **Models:** allowlist (e.g. one vendor + one model family) to limit support blast radius.
- **BYOK credit:** optional discount when Customer brings own keys—document in order form.

## Seat / MAU definitions (define in order form)

- **Seat:** named analyst with SSO identity accessing copilot UI in a billing period.
- **MAU:** distinct analysts with ≥1 turn—better for bursty teams; cap max concurrent if gaming is a concern.

## Analytics add-on (optional)

- If [org analytics](saarthi-pro-org-analytics-multitenant-spec.md) is Vendor-hosted: price as **% of platform** or **fixed** per TB ingested—with **data minimization** to keep cost predictable.

## Related

- [Saarthi Pro vs OSS](saarthi-pro-vs-oss.md)
- [Legal order-form addenda outline](saarthi-pro-legal-order-form-addenda-outline.md)
