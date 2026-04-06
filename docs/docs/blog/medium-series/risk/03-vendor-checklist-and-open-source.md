<!-- Subtitle: Keeping intelligence useful without turning your data into someone else’s asset -->

## The collaboration paradox

Fraud actors share tactics quickly. Legitimate institutions often **cannot** share raw customer data at the same speed. That isn’t cowardice; it’s law, contracts, and basic respect for privacy.

So the useful question is not “should we share everything?” It’s **what can we share that raises the cost of abuse without leaking PII?**

Hashes of device fingerprints, typology labels, mule-account indicators, and network reputation signals can travel **if** the pipeline is designed for de-identification from day one. Tarka is built to run **in your environment**, which keeps the raw data under **your** access controls while still letting you participate in community-style defense if you choose to.

## Open source is a governance choice, not a hobby

You can run **strong commercial fraud vendors** and still use the same **diligence** below—many mature programs combine **network intelligence from SaaS** with **case data, audit logs, and overrides** they own. Open source is one way to own that second half; it is not a requirement to **care** about transparency.

Publishing code changes the conversation with procurement and IT:

- **Transparency:** your security team can read the integration points instead of trusting a black-box diagram.
- **Portability:** you’re not locked into a single cloud region or pricing tier to keep the lights on.
- **Evidence:** when something breaks, you can bisect a version instead of waiting for a vendor maintenance window.

The cost is real: you need people who can run containers, read release notes, and patch dependencies. For many mid-size and large shops, that cost is **already** paid; they’re just spending it on bespoke glue around closed APIs.

## A practical vendor and platform checklist

Use this when comparing Tarka to SaaS tools or to an in-house build:

**Data and residency**

- Where does raw PII sit at rest? Who has admin keys?
- Can we run scoring entirely inside our VPC or sovereign region?

**Explainability**

- What does an analyst see in 60 seconds when a VIP is blocked?
- Can we export a decision record suitable for audit, not just a dashboard screenshot?

**Policy lifecycle**

- How do we test a rule change before production?
- Can we roll back a model version without a contract negotiation?

**Operational fit**

- Does high-volume traffic have a **sync** and an **async** path, or only one?
- What breaks if graph or ML is slow: do we hard-fail or degrade gracefully?

**Community and intelligence**

- If we participate in shared signals, **what exactly** leaves our boundary?
- Can we opt out per geography or product line?

## “Way forward” from a program owner’s view

Near term, we’re focused on **boring reliability**: simpler first-run installs, clearer security posture for enterprises, SDK parity across web and mobile so your channels don’t diverge.

Longer term, the product thesis stays the same: **modular fraud infrastructure** you can grow into. Start with decisions and cases; add graph and ML when your losses justify the complexity.

You don’t owe any vendor a five-year roadmap commitment. You owe your customers **consistent, explainable treatment** and your board **controls they can describe**.

## One line to steal for internal memos

> Fraud tooling should be as inspectable as your ledger: if you can’t trace the line items, you don’t have a control—you have a hope.

If Tarka helps you pass that bar, use it. If something else does, use that. The bar matters more than the logo.

---

*Repository: [github.com/pamu512/tarka](https://github.com/pamu512/tarka) · Security disclosure: see `SECURITY.md` in the repo*
