# Saarthi Pro — customer API & integration contract change policy (draft)

> **Internal commercial / engineering policy draft.** Not legal advice. Final notice windows, liability caps, and definitions belong in the MSA, DPA, and order form. Use this document to align sales, support, and engineering before customer-facing publication.

## 1. Two version lines

| Line | What it versions | Who consumes it |
|------|------------------|-----------------|
| **Integration contract** | Stable JSON/OpenAPI snapshot from the investigation agent (`contract_version` on `GET /v1/integration`, changelog in [CHANGELOG_INTEGRATION.md](CHANGELOG_INTEGRATION.md)) | All deployments; adapters map into this surface. |
| **Customer API** | The buyer’s Case, Graph, Decision, or other HTTP APIs the **adapter** calls | Adapter maintainers (Pro engineering or customer team). |

Breaking changes are classified **per customer API** and **per integration contract** independently. A new `contract_version` may ship without any change to customer APIs; a customer API major bump may require adapter work without a contract major bump.

## 2. Breaking vs compatible (customer API)

Treat a customer API change as **breaking** to the adapter when it would cause **incorrect** or **unsafe** behavior without code or config updates, including:

- Removed endpoints, fields, or enum values that the adapter relies on.
- Semantic changes (same field name, different meaning or units).
- Auth model changes that invalidate the current credential or token flow.
- Pagination or rate-limit behavior changes that require client logic changes to remain correct.

**Compatible** changes (typically no adapter release required): additive optional fields, new endpoints unused by the adapter, backward-compatible extensions documented by the customer.

Security-critical fixes on the customer side (see §6) may be treated as breaking for scheduling even if the OpenAPI diff looks minor.

## 3. Notice and joint certification (maintained adapter tiers)

For **Saarthi-maintained** adapters, use the following as **default commercial targets**; the executed **MSA and order form** control if they differ (e.g. regulated stacks with fixed vendor cadence).

1. **Written notice** from the customer (or their vendor) at least **90 calendar days** before a breaking customer API change reaches the adapter’s production target environment, unless a shorter (or longer) window is agreed in writing for that platform or program.
2. **Technical specification**: release notes, diff or new OpenAPI, sandbox or staging endpoint, and test accounts.
3. **Joint test window**: agreed calendar window where Pro runs the adapter’s automated suite and optional golden scenarios against customer UAT. **Default target: 2–4 weeks** before production cutover unless the **MSA, SOW, or order form** sets a different duration, start date, or exit criteria for that program.
4. **Adapter release**: versioned adapter artifact (and release notes) shipped before production cutover; customer acknowledges go-live or requests rollback path.

Customer-built adapters may adopt the same norms voluntarily; Pro’s runtime **integration contract** changelog still applies to them.

## 4. Integration contract (`contract_version`) changes

Defaults below are **engineering and commercial targets**; the executed **MSA, product appendix, or order form** may specify **longer** deprecation periods, joint migration windows, or emergency carve-outs (aligned with §3).

- **Minor / patch** contract updates (new optional fields, new tools behind flags, documentation): follow [CHANGELOG_INTEGRATION.md](CHANGELOG_INTEGRATION.md); adapters should tolerate unknown JSON fields.
- **Major** contract updates (removed tools, renamed required fields, incompatible semantics): documented in the changelog with migration notes. **Default target:** a **deprecation window** of at least **one minor contract release** before removing or breaking behavior, unless security or compliance forces a shorter path (see §5).
- Customers with `INTEGRATION_PROFILE_ID` set should treat profile documentation and conformance tests as part of their release gate.

## 5. Emergency and security exceptions

Either party may require an **expedited change** (shorter notice) for:

- Confirmed or actively exploited vulnerabilities.
- Regulatory or issuer mandates with a fixed deadline.

The requesting party provides written justification and the narrowest change set. Pro may ship an adapter hotfix or temporary feature flag; the customer may need to accept an emergency maintenance window. **This section does not waive MSA liability limits**—it only describes operational intent.

## 6. What we publish externally (when Pro GTM is cleared)

- This policy (or a shortened customer summary).
- Link to integration contract doc and changelog.
- Reference to **golden CI profiles** (e.g. full, no_graph, no_case) as conformance vocabulary.

## 7. Related artifacts

- [Investigation agent integration contract](investigation-agent-integration-contract.md)
- [Adapter strategy & pricing (internal)](saarthi-pro-adapter-strategy-and-pricing.md)
- [Saarthi Pro roadmap](saarthi-pro-roadmap.md) · [adapter catalog & certification](saarthi-pro-adapter-catalog-and-certification.md)
- Adapter template: `templates/cookiecutter-investigation-integration-adapter/` in the fraud-stack repo
- CI: job `test-investigation-agent-golden-matrix` in `.github/workflows/ci.yml`
