# Saarthi Pro — adapter-first strategy & illustrative pricing (internal draft)

> **Internal / maintainer use only.** Not legal, tax, or financial advice. **Do not** paste illustrative bands into customer quotes until commercial terms are finalized with counsel and finance. For **buyer-facing** positioning (no dollar figures), use [Saarthi Pro vs OSS](saarthi-pro-vs-oss.md).

## 1. Product thesis: Pro = runtime + **maintained adapter**

**OSS** remains the reference copilot and integration target for teams that own their own APIs (e.g. Tarka-shaped case/graph/decision services).

**Saarthi Pro** should be positioned primarily as:

1. **Copilot runtime** (hardening, governance profiles, assurance modes, optional hosted deployment).
2. **A versioned integration contract** (“Saarthi capability surface”) that maps to any fraud stack.
3. **Vendor-owned adapter**: we **ship, test, and maintain** the connector that implements that contract against **their** APIs (or a thin sidecar they host).

**Why this wins “plug and play”:** buyers pay to **not** own adapter breakage when the case system, audit API, or auth model changes. The moat is **operational**, not a secret model.

## 2. Packaging tiers (suggested)

| Tier | Who builds adapter | What Pro maintains | Typical buyer |
|------|--------------------|--------------------|---------------|
| **Runtime + Support** | Customer (their team implements contract) | Copilot binary, security patches, docs, best-effort integration guidance | Large internal platform teams |
| **Certified adapter (single stack)** | Saarthi Pro engineering | Adapter code, contract tests, release notes per **their** API version bumps; excludes changes to **their** product roadmap without change order | Mid-market and enterprise with one primary case/alert system |
| **Certified adapter + SLA** | Saarthi Pro | Above + response-time SLAs, named versions, security review of adapter, quarterly compatibility certification | Regulated / procurement-heavy |
| **Managed sidecar** | Saarthi Pro hosts or co-manages connector deployment | Adapter + infra runbook, upgrades, monitoring hooks | Buyers who want minimum internal ops |

Optional add-ons (priced separately): SSO/SCIM, VPC/residency wrapper, extra adapter (second system), custom skills/playbooks review, professional services for workflow (not adapter).

## 3. What “maintain the adapter” includes (define in MSA)

**In scope (illustrative):**

- Compatibility with **documented** Saarthi integration API version `vN`.
- Updates when **documented** customer API versions change within the **same major** integration profile (e.g. “Salesforce FSC read patterns v2”).
- Security patches in adapter and runtime; CVE response per support tier.
- Conformance test suite green in CI for that adapter profile.

**Out of scope (unless change order):**

- Customer bespoke schema changes without notice.
- New data domains (e.g. “add sanctions screening API”) — new capability = new SOW or tier bump.
- Performance of **their** backend; adapter tuning within agreed rate limits only.

## 4. Pricing model (components)

Mix **recurring platform** + **per-adapter** + **entitlements** so margin scales with maintenance burden:

| Component | Basis | Rationale |
|-----------|--------|-----------|
| **Platform subscription** | Per deployment / per org / year | Runtime, updates, governance features, support channel |
| **Maintained adapter fee** | Per **connected system profile** / year | Directly maps engineering + QA cost |
| **Seats or MAU** (optional) | Analysts using copilot | Aligns value to usage; avoid for pure API-only if awkward |
| **SLA uplift** | % of subscription or fixed add-on | 24×7 vs business hours |
| **Implementation / onboarding** | Fixed SOW once | First adapter + conformance sign-off |

Avoid **unlimited** adapter changes for one flat fee unless you want margin collapse.

## 5. Illustrative annual pricing (USD, **order-of-magnitude** anchors)

These are **starting negotiation bands**, not quotes. Calibrate to your cost to hire/maintain one integration engineer + support rotation.

### 5.1 Comparable markets (why these bands exist)

- **Enterprise iPaaS / connector platforms** (Workato, Mulesoft, Boomi): often **mid–high five to six figures** ACV before volume; heavy PS for complex ERP/case shapes.
- **ELT / managed connectors** (Fivetran-class): **connector + usage** pricing; maintenance is the product.
- **OSS enterprise subscriptions** (Red Hat model): **per socket or per cluster** + support; 20–35% of list for multi-year deals is common pattern (illustrative only).
- **AI copilot add-ons** (Microsoft 365 Copilot–class): **per user per month** retail; enterprise EAs are opaque—use as ceiling for **seat** component only, not whole Pro.
- **Integration professional services** (US/EU blended): roughly **$150–250/hr** equivalent in SOWs; a serious adapter + test + docs is rarely &lt; **a few weeks** of focused work.

### 5.2 Suggested **illustrative** ACV ladders (adapter maintained by Pro)

| Segment | Platform (runtime + standard support) | First maintained adapter (1 system) | SLA / premium support add-on | Typical onboarding SOW (one-time) |
|---------|--------------------------------------|-------------------------------------|------------------------------|-------------------------------------|
| **Growth** (single env, business-hours) | **$18k–$35k / yr** | **$25k–$50k / yr** | **+$8k–$15k / yr** | **$15k–$40k** |
| **Mid-market** | **$35k–$75k / yr** | **$50k–$120k / yr** | **+$15k–$35k / yr** | **$40k–$90k** |
| **Enterprise** (VPC, change windows, named CSM) | **$75k–$150k+ / yr** | **$120k–$250k+ / yr** per primary stack | **+$35k–$80k+ / yr** | **$90k–$250k+** |

**Second adapter** (e.g. case system + separate graph vendor): often **50–80%** of first adapter ACV if contract surface is shared; **full price** if greenfield API shape.

**Seats** (optional): **$15–$40 / user / month** for analyst-facing SKUs *in addition* to platform where procurement expects per-seat AI line items—cap or bundle into platform to avoid double-counting.

### 5.3 Customer-built adapter (Pro runtime only)

If they maintain the adapter:

- **Platform + support:** roughly **50–65%** of the “platform” column above for equivalent segment (no adapter maintenance).
- **Certification fee (optional):** one-time **$8k–$25k** to run conformance suite, issue compatibility letter for a **fixed** API version (good for banks that self-build).

## 6. Competitive framing (honest)

- **Vs. generic LLM + SI:** Pro is cheaper **per year** than a permanent integration team **only if** adapter scope is **bounded** and contract is stable.
- **Vs. fraud suite “AI module”:** Pro wins on **transparent tool trace + BYOK + your stack**; you lose on **single SKU** and **embedded workflow** unless adapter is seamless.
- **Vs. full Tarka:** Pro without Tarka must **prove** adapter ROI; price should reflect **avoided headcount** (0.5–1.5 FTE integration + on-call).

## 7. Engineering artifacts (shipped in OSS reference → strengthens Pro)

| Artifact | Location / use |
|----------|----------------|
| **Versioned integration snapshot** | `GET /v1/integration` + `integration` on `GET /v1/health` — `contract_version`, `profile_id` (`INTEGRATION_PROFILE_ID`), upstream booleans, enabled tools, **families** for mapping. |
| **Contract doc** | [investigation-agent-integration-contract.md](investigation-agent-integration-contract.md) |
| **Unit tests** | `services/investigation-agent/tests/test_integration_contract.py` |
| **Live smoke** | `scripts/ci/check_integration_contract.py --base-url …` |
| **Upstream mock (stdlib)** | `scripts/integration_adapter_mock/server.py` — stub Case/Graph/Decision paths for adapter dev |
| **OSS agent image** | `services/investigation-agent/Dockerfile` (monorepo root build context); CI **`docker-build`** |

**Shipped in OSS reference:** profile-scoped **golden tests** + CI matrix (`test-investigation-agent-golden-matrix`), adapter **cookiecutter** (`templates/cookiecutter-investigation-integration-adapter/`), and **[customer API change policy](saarthi-customer-api-change-policy.md)** (notice, joint certification, exceptions). **Pro-branded** images, `RELEASE.md`, and registry publish paths → **private** [Saarthi-pro](https://github.com/pamu512/Saarthi-pro).

**Commercial playbooks (fraud-stack docs):** Phase 1–3 **templates and specs** — [roadmap index](saarthi-pro-roadmap.md#phase-13-artifact-index-quick-links) (upgrade path, release notes, support severity, certification, SSO/SCIM, DPA, VPC, runbooks, SOW, evidence v1 mapping, analytics, economics, legal exhibits).

## 8. Related docs

- [Saarthi Pro roadmap](saarthi-pro-roadmap.md)
- [Distribution & contract parity](saarthi-pro-distribution-and-contract-parity.md)
- [Adapter catalog & certification](saarthi-pro-adapter-catalog-and-certification.md)
- [Assurance, warranties & liability (positioning)](saarthi-pro-assurance-liability-positioning.md)
- [Saarthi customer API change policy](saarthi-customer-api-change-policy.md)
- [Saarthi Pro vs OSS](saarthi-pro-vs-oss.md) (buyer-facing comparison; no pricing)
- [Investigation Agent Project](../projects/investigation-agent-project.md)
- [Investigation Copilot — intended use & data flows](investigation-agent-intended-use-and-data-flows.md)
