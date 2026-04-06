# Saarthi Pro — support severity definitions (internal)

> **Internal default targets** for support runbooks and SLAs. **Executed response times** belong in the **order form / SLA exhibit**. Severity is agreed with the customer per ticket.

## Severity matrix

| Severity | Customer impact | Examples | Default target (business hours tier) | Default target (24×7 SLA tier) |
|----------|-----------------|----------|--------------------------------------|--------------------------------|
| **P1 — Critical** | Production copilot **unavailable** or **unsafe** (data leak path, auth bypass) for many users | Agent crash loop; wrong tenant data returned; integration contract completely wrong vs docs | Ack **1 h**; engaged workaround **4 h** | Ack **30 m**; engaged **2 h** |
| **P2 — Major** | Core workflow **degraded**; no safe workaround | Tool loop fails for primary case API; streaming broken; strict assurance stuck on | Ack **4 h**; plan **1 bd** | Ack **1 h**; plan **4 h** |
| **P3 — Minor** | Limited impact; workaround exists | Single tool error handling; UI nits in gateway; doc typo causing confusion | Ack **1 bd** | Ack **4 h** |
| **P4 — General** | Questions, feature asks, roadmap | How-to, certification evidence, RFP answers | Best effort queue | Best effort queue |

## Scope boundaries

- **Customer API outages** or **third-party LLM** incidents: support assists with **diagnosis** and adapter/config guidance; RCA may sit with customer or provider.
- **Adapter bugs** (Pro-maintained): in-scope per [adapter strategy](saarthi-pro-adapter-strategy-and-pricing.md) MSA; customer schema drift without notice may be **change order**.

## Escalation

1. On-call / support queue owner assigns severity with customer.
2. P1/P2: notify engineering lead + (if regulated) customer success director.
3. Security: follow [managed operations runbook](saarthi-pro-managed-operations-runbook.md) security section.

## Related

- [Managed operations runbook](saarthi-pro-managed-operations-runbook.md)
- [Assurance & liability positioning](saarthi-pro-assurance-liability-positioning.md)
