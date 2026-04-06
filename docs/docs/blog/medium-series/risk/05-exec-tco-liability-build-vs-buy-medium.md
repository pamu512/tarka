<!--
MEDIUM PUBLISHING
Title:    Fraud Stack Decisions Your Board Actually Cares About
Subtitle: TCO, liability, and support—without the ports and acronyms.
-->

Fraud Stack Decisions Your Board Actually Cares About

*TCO, liability, and support—without the ports and acronyms.*

---

Engineering wants architecture. Fraud ops wants fewer 2 a.m. tickets. Your **CFO** and **GC** want to know **what costs money**, **who is accountable when something breaks**, and **whether you can explain a bad outcome** without inventing a story.

This note is for **executive sponsors** choosing between **another SaaS renewal**, **a hybrid**, or **running open infrastructure** (including projects like **Tarka**). No product pitch—just the questions that belong in a steering deck.

## Total cost is not the invoice line

**Vendor TCO** usually includes: per-transaction fees, implementation, professional services, **integration maintenance**, and the **opportunity cost** of policy changes waiting on vendor roadmaps.

**Self-hosted / open-source TCO** usually includes: cloud or on-prem compute, **people** who can deploy and patch, **security** reviews, and **on-call** for your own stack.

The cheaper option on paper is often the **more expensive** one if you ignore **false-positive support load**, **lost revenue** from mystery declines, or **audit remediation** after an exam finds weak model governance.

Ask finance to model **both** sides with **three years** of horizon, not renewal price alone.

## Liability follows the decision, not the logo

When a customer is harmed or a regulator asks questions, **your institution** is in the narrative—not the vendor’s sales deck. Contracts may indemnify for **bugs**, rarely for **your** use of scores in policy.

Board-level questions worth asking:

- Who **signs off** on thresholds that block customers?
- Do we have a **durable record** of what we knew at decision time (scores, factors, versions)?
- If the vendor changes the model **silently**, do we **detect** it before customers do?

**Open source** does not remove liability; it can **improve defensibility** because **you** control versioning, logging, and replay—if you invest in operating it well.

## Support model: who answers at 3 a.m.?

**Vendor SLA:** named response times, escalation paths, and whether **forensic** questions cost extra.

**In-house:** your runbook, paging rotation, and whether **one team** owns “fraud product” end to end.

Many mature programs use a **hybrid**: vendor for global network intelligence, **your** platform for **case data, audit trail, and overrides**. The executive job is to ensure **one named owner** for the **combined** system, not two teams blaming each other in an incident.

## Build vs buy vs hybrid (simple frame)

- **Buy** when time-to-value and **network effects** dominate and your contract guarantees **minimum transparency** (definitions, versions, exports).
- **Build** when **differentiation**, **data residency**, or **audit** require **you** to own the artifact.
- **Hybrid** when you keep a vendor score but **mandate** logging, **shadow** evaluation, and **your** case tooling—often the **lowest-risk first step**.

## What we’re optimizing for at Tarka

We publish **open, modular** software so teams can **own** definitions and evidence **without** pretending operations are free. That shifts **spend** from opaque licenses to **skilled people**—which many firms already employ; they’re just paying twice today.

**Repository:** [github.com/pamu512/tarka](https://github.com/pamu512/tarka) · **Security:** see `SECURITY.md` in the repo.

---

**Suggested Medium topics:** Leadership, Fintech, Risk Management, Startup, Fraud Prevention

**Companion:** `risk/03-vendor-checklist-and-open-source.md`, `risk/04-opaque-fraud-metrics-demanding-clarity-medium.md`
