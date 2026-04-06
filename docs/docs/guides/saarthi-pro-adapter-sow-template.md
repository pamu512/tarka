# Saarthi Pro — maintained adapter statement of work (SOW) template

> **Internal commercial skeleton.** Not legal advice. Counsel must finalize scope, fees, and liability caps.

---

## SOW — [Customer] × [Vendor] — Adapter [integration_profile_id]

**Effective:** [date]  
**MSA reference:** [link/id]  
**Profile id:** `[INTEGRATION_PROFILE_ID]` (matches agent config and [adapter catalog](saarthi-pro-adapter-catalog-and-certification.md))

### 1. Objective

Implement and maintain an HTTP adapter (or configuration) mapping Customer’s **[Case / Graph / Decision]** APIs to the Saarthi **integration contract** version **[contract_version]** at delivery.

### 2. Deliverables

- Adapter codebase or sidecar image: [repo / registry path]
- **Bronze** certification complete per [certification checklist](saarthi-pro-certification-checklist.md) by [milestone date]
- **Silver** (if purchased): golden profiles [list] green in UAT by [date]
- Runbook: auth rotation, rate limits, known limitations

### 3. Assumptions

- Customer provides **sandbox/UAT**, test accounts, and OpenAPI or equivalent within [X] days of kickoff.
- Customer API changes follow [customer API change policy](saarthi-customer-api-change-policy.md).

### 4. Out of scope (unless change order)

- New data domains (sanctions, credit bureaus, …)
- Performance of Customer backends beyond agreed rate-limit tuning
- Custom workflow UI outside investigation agent

### 5. Fees

- Implementation: [fixed / T&M cap]
- Annual maintenance: [tier reference to pricing doc]

### 6. Acceptance

Sign-off when Silver (or Bronze) checklist is complete and Customer integration lead approves in writing.

---

## Related

- [Adapter-first strategy & pricing](saarthi-pro-adapter-strategy-and-pricing.md)
- [Customer API change policy](saarthi-customer-api-change-policy.md)
