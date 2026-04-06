# Saarthi Pro — legal & order-form addenda outline (for counsel)

> **NOT LEGAL ADVICE.** Headings for counsel to draft exhibits. Must align with [assurance & liability positioning](saarthi-pro-assurance-liability-positioning.md).

## Exhibit A — Integration contract

- Reference **`contract_version`** and URL or doc path to integration changelog.
- Customer responsibility: tolerate unknown JSON fields on minor bumps unless major announced.

## Exhibit B — SLA (if purchased)

- Attach [support severity](saarthi-pro-support-severity.md) **targets** as negotiated numbers.
- Exclusions: Customer APIs, LLM provider, internet, force majeure.

## Exhibit C — DPA & subprocessors

- Use [DPA template](saarthi-pro-dpa-subprocessor-template.md) as starting point; attach live subprocessor URL.

## Exhibit D — Maintained adapter (if purchased)

- `integration_profile_id`, golden profiles certified, [SOW](saarthi-pro-adapter-sow-template.md) reference.
- Change notice: [customer API change policy](saarthi-customer-api-change-policy.md) defaults or MSA overrides.

## Exhibit E — Optional indemnity / enhanced warranty (Phase 3)

- **Narrow scope:** e.g. infringement of Pro-distributed **adapter code** only; cap = fees paid in [12] months.
- **Explicitly exclude:** LLM output correctness, Customer data in prompts, third-party APIs.
- **No** contradiction of “no guarantee of factual accuracy” in base terms.

## Exhibit F — Security & residency

- Reference [residency & VPC](saarthi-pro-residency-vpc-deployment.md) deployment pattern chosen.
- Pen test cadence, vulnerability disclosure contact.

## Related

- [Economics appendix](saarthi-pro-economics-packaging-appendix.md)
- [Managed operations runbook](saarthi-pro-managed-operations-runbook.md)
