# Saarthi Pro — assurance, warranties & liability (positioning draft)

> **Internal positioning for sales, solutions, and counsel.** Not legal advice. Final warranties, caps, and exclusions live in the **MSA, DPA, and order form**. This doc prevents **accidental** over-promise in demos and RFPs.

## What the product is (and is not)

- Saarthi Pro is an **AI-assisted investigation copilot**: the model **proposes** steps and prose; **systems of record** (case, graph, decision APIs) **answer** via tools; **humans** decide outcomes that matter for compliance and litigation.
- It is **not** an autonomous decision system, not a substitute for adjudication, and **not** a guarantee of factual correctness of natural-language summaries.

## Grounding and “AI accuracy” (procurement alignment)

OSS and Pro share the same **technical** grounding stack unless release notes say otherwise: claims trailers, deterministic overlap hints, optional judge pass, strict assurance mode, truncation limits. See [Investigation Agent Project](../projects/investigation-agent-project.md) (gaps table).

**Positioning lines that stay true:**

- We **measure and expose** structured signals (e.g. tool errors, `claims_deterministic_support`, assurance refusals)—useful for **your** monitoring and QA.
- We **do not** warrant that every sentence is **factually complete** or **litigation-ready** without human review.
- **Strict assurance mode** reduces certain failure modes (e.g. prose when tool claims are unsupported); it does **not** replace legal or fraud ops review.

**Avoid:** “Guaranteed hallucination-free,” “certified for court submission,” “validates all outputs.”

## Blast radius and responsibility split (MSA prep)

Use this **engineering** split when counsel drafts terms:

| Layer | Typical responsibility |
|-------|-------------------------|
| **Customer APIs & credentials** | Customer ensures authZ/authN, rate limits, and data in case/graph/decision systems are correct. Wrong data in SoR → wrong tool output. |
| **Adapter (Pro-maintained or customer-built)** | Mapping bugs, version skew against customer API, misconfigured URLs—scoped in adapter SOW / [change policy](saarthi-customer-api-change-policy.md). |
| **Copilot runtime** | Bugs in tool loop, prompt templates shipped by Pro, integration snapshot correctness vs documented contract. |
| **LLM provider (BYOK or bundled)** | Model behavior, availability, subprocessors—customer’s or vendor’s DPAs per deployment. |

**Powerful tools** (replay, label ingest, graph expansion) remain **high blast radius**: contractual controls should reference **maker–checker**, **RBAC upstream**, and **network isolation**, not “the AI is safe.”

## Optional commercial add-ons (Phase 3 roadmap)

Indemnity, enhanced support credits, or fixed remediation SLAs belong in **separate order-form language** reviewed by counsel. They must **not** contradict the rows above unless explicitly negotiated.

## Related

- [investigation-agent-assurance-modes.md](investigation-agent-assurance-modes.md)
- [investigation-agent-intended-use-and-data-flows.md](investigation-agent-intended-use-and-data-flows.md)
- [Legal order-form addenda outline](saarthi-pro-legal-order-form-addenda-outline.md) (counsel)
- [Saarthi Pro roadmap](saarthi-pro-roadmap.md)
- [Saarthi Pro vs OSS](saarthi-pro-vs-oss.md)
