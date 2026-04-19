# Feature pack: regulated markets (fintech, banking, crypto, similar)

**Status:** **Optional operational and integration pattern** — not a separate binary or license tier in the OSS repo. Use this page as a **checklist** when procurement, risk, or policy teams require stronger **ingress integrity**, **auditability**, and **data-boundary** clarity than a default single-region SaaS-style deployment.

**Audience:** Teams in **highly regulated** sectors (e.g. banking, payments, digital assets, broker-dealers) and **security-sensitive** programs that must justify controls to auditors and regulators *without* claiming certifications this repository does not confer.

---

## What this “pack” is

A **bundle of documented capabilities** you enable together:


| Theme                              | OSS / deployment levers                                                                                         | Notes                                                                                                                                                                                                                             |
| ---------------------------------- | --------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Transport & request integrity**  | TLS, optional **certificate pinning** (mobile), `**REQUEST_SIGNATURE_SECRET`** on `POST /v1/decisions/evaluate` | See [TLS pinning and signed requests](./tls-pinning-and-signed-requests.md). Signing proves **possession of a server-held secret** at the integration boundary (service-to-service or gateway), not “only genuine end-user apps.” |
| **Device & session assurance**     | `**device_context`**, `**/v1/attestation/***`, Play Integrity / App Attest in native SDKs                       | Attestation **strength depends on platform and server verification**; document your trust tier per OS.                                                                                                                            |
| **Replay & abuse**                 | Redis-backed **replay signature** checks, rate limiting                                                         | Configure Redis and policies for production traffic.                                                                                                                                                                              |
| **Audit & explainability**         | Decision **audit** with trace IDs, `**inference_context`**, case linkage                                        | Supports **explainable** decisions for internal review; map to your **retention** and **access control** policies.                                                                                                                |
| **Data residency & subprocessors** | **Self-hosted** stack; bring-your-own **LLM** for investigation agent                                           | Critical for regulated AI: see [investigation-agent-llm-data-flow](./investigation-agent-llm-data-flow.md). No public-cloud LLM required.                                                                                         |
| **Governance**                     | Rule packs, challenge policies, `**/v1/ops/calibration-status`**, experiment registry                           | Supports **change control** narratives (what shipped, when, with what benchmarks).                                                                                                                                                |


---

## Deployment pattern (recommended)

1. **Isolate** the Decision API behind an **API gateway** (mTLS gateway → decision-api) in production.
2. Enable **request signing** at the gateway **or** in-process via `**REQUEST_SIGNATURE_SECRET`** where appropriate for **machine clients**; avoid embedding shared secrets in **untrusted** mobile apps (use gateway-issued credentials instead).
3. Use **pinning** on mobile clients that can justify the **rotation** operational cost; set `**metadata.tls_pinning_verified`** only when the client actually verified pins.
4. Run **benchmarks** and **counter parity** checks on a schedule ([counter-replay-parity](./counter-replay-parity.md), CI workflows) and **retain artifacts** for audits.
5. Document **subprocessors**, **regions**, and **key rotation** in your own **security pack** (this repo does not ship legal templates).

---

## Honest limits (read before procurement claims)

- **Obfuscation** of client SDKs (ProGuard/R8, etc.) is a **cost-raising** measure against casual reverse engineering; it is **not** a cryptographic guarantee. Prefer **attestation**, **signing**, and **server-side** policy.
- **Envelope encryption** of JSON bodies (decrypt only on the fraud stack) is a possible **future** optional layer; it **does not** by itself prove app authenticity because **public keys** in clients are extractable. Treat any “decrypt failure ⇒ malicious” policy with care (see internal security review).
- This project **does not** certify **SOC 2**, **PCI**, **ISO 27001**, or **jurisdictional** compliance; your organization maps controls to frameworks. For a short orientation on **readiness** vs attestation, see [compliance readiness (SOC 2 / PCI / ISO)](./compliance-readiness-soc2-pci-iso.md).

---

## Related documentation

- [Compliance readiness: SOC 2, PCI, ISO 27001](./compliance-readiness-soc2-pci-iso.md)  
- [TLS pinning and signed requests](./tls-pinning-and-signed-requests.md)  
- [SDK scorecard](./sdk-scorecard-2026-01.md) · [Mobile SDK project](../projects/sdk-mobile-project.md)  
- [Investigation agent — LLM data flows](./investigation-agent-llm-data-flow.md)  
- [Aspirational gaps execution plan](./aspirational-gaps-execution-plan.md) (longer-term hardening)  
- [Saarthi Pro vs OSS](./saarthi-pro-vs-oss.md) (commercial packaging, if applicable)

---

## Versioning

Update this page when new **optional** security levers ship (e.g. additional middleware, schema versions). Reference **git tag** or release note when attaching evidence to customer security questionnaires.