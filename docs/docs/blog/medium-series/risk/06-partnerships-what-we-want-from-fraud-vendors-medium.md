<!--
MEDIUM PUBLISHING
Title:    What We Want From Fraud Vendors (Including When We Compete)
Subtitle: Clear metrics, honest change control, and room for hybrid stacks—not a pile-on, a spec.
-->

What We Want From Fraud Vendors (Including When We Compete)

*Clear metrics, honest change control, and room for hybrid stacks—not a pile-on, a spec.*

---

We ship **open-source** fraud infrastructure (**Tarka**). That puts us in tension with parts of the vendor ecosystem—and **alignment** with others. This post is for **vendor teams**, **partners**, and **buyers** who already run a strong commercial stack and wonder why we still argue about **transparency**.

We are **not** claiming every vendor is opaque. Many teams ship **reason codes**, **sandboxes**, **versioned models**, and **serious** professional services. The industry problem is **inconsistent**: what’s marketed as “AI” sometimes **isn’t** operationally inspectable under real contracts. We want **that gap** to close—even when the buyer keeps your product.

## What “good” looks like (buyer-side checklist)

If you already do most of this, you’re the **reference** we point buyers toward:

1. **Documented definitions** for every headline KPI (denominator, lag, segment).
2. **Production metadata** on scores: model or ruleset **ID**, **timestamp**, and **top factors** (aggregated is fine).
3. **Change management**: customer-visible shifts tied to **release notes** or notice windows—not “trust us, it’s better.”
4. **Exports and APIs** that let the buyer **log** decision-time context into **their** warehouse and case tools.
5. **Clear boundaries** on **IP vs privacy**: what can leave the tenant, under what **DPA**, with **redaction** defaults.

When vendors meet that bar, **open stacks** and **SaaS** can coexist: you bring **network intelligence**; the buyer brings **policy, audit, and UX** on their side.

## Hybrid stacks are normal—and healthy

The winning pattern is often **vendor score + buyer-owned record**: correlation IDs, immutable logs, replay in **their** environment, step-up rules **they** control. Tarka is one way to own that **right-hand side**; some buyers will use **in-house** builds or other OSS.

We’re **not** asking you to open your models. We **are** asking for **contract-grade** commitments on **explainability outputs** and **versioning** so hybrid architectures don’t rot into “black box in prod, spreadsheet in crisis.”

## Where we’d like to partner

- **Data and standards:** shared interest in **safe** signal exchange (hashed identifiers, typologies) without **PII** leakage.
- **Technical:** clean **webhooks**, **batch exports**, **evaluation** hooks for holdouts and shadow scoring.
- **Commercial:** respect when a buyer chooses **self-hosted** for **residency** or **governance** while keeping **your** network product for **global** risk.

If you’re building that way, we’re **allies** on **buyer education** even where we “compete” for footprint.

## A line we won’t cross

We will keep saying: **decisions should carry evidence** your customer and your auditor can trace. If your roadmap already delivers that under **real** contracts, we’ll **say so**—and mean it.

**Tarka:** [github.com/pamu512/tarka](https://github.com/pamu512/tarka)

---

**Suggested Medium topics:** Fintech, Fraud Prevention, B2B, Partnerships, Cybersecurity

**Companion:** `risk/04-opaque-fraud-metrics-demanding-clarity-medium.md`
