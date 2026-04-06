<!--
MEDIUM PUBLISHING
Title:    Your Vendor’s “Fraud Rate” Is a Story. Make Sure You Know the Plot.
Subtitle: Single-number fraud metrics are easy to sell and easy to misuse. Here’s how to verify them, what to ask for first, and why vendors aren’t the only ones facing trade-offs.
-->

Your Vendor’s “Fraud Rate” Is a Story. Make Sure You Know the Plot.

*Single-number fraud metrics are easy to sell and easy to misuse. Here’s how to verify them, what to ask for first, and why vendors aren’t the only ones facing trade-offs.*

---

If you’ve ever presented a fraud KPI to leadership, you know the comfort of a clean headline: **fraud down 18%**, **chargebacks flat**, **approval rate up**. If you’ve ever sat with support while a good customer asks *why* they were blocked, you know how fast that comfort disappears.

Third-party fraud engines often reinforce the same habit. They ship **scores**, **bands**, or **rollup rates** that look decisive in a dashboard. Too often they hide the definitional choices underneath: what counts as an attempt, what counts as fraud, how chargeback lag is handled, which traffic segments moved. The number isn’t a lie; it’s a **compression**. Compressions are fine for executive summaries. They’re dangerous when product, ops, and risk **treat them as sufficient** to steer policy or explain a decline to a human being.

This piece is for people who buy, deploy, or govern those tools—not to bash vendors, but to treat vendor metrics as **claims to verify**, and to negotiate **minimum viable transparency** before you optimize the headline.

## What the field actually reports

You don’t need a peer-reviewed paper to show the pattern is real—only that it’s **recurring**. Trade press and payments outlets (e.g. PaymentsSource, PYMNTS, The Paypers) have run merchant-side stories about **reconciling declines to chargebacks**, **false-positive pain**, and **limited signal-level transparency** from scoring providers. Fraud and payments conferences (Money20/20, RSA, vendor-led fraud summits) routinely include **anonymized** talks: teams discovering high false-positive rates, then fixing them only after **sample exports**, **holdouts**, or **negotiated access** to richer outputs. **Strong vendor programs** already publish clear definitions and ship **versioned** outputs; this article is for when **sales promises** and **production reality** don’t match—or when your **contract** doesn’t guarantee what you need to operate.

Regulators, meanwhile, have pushed **explainability, auditability, and third-party model governance** in automated decisioning—not fraud-only, but fraud scoring sits in the same bucket when it affects customers. None of that proves every vendor is opaque; it proves **opacity has a cost** that supervisors and operators already recognize.

Two U.S. references that anchor that theme (your mileage varies by product and jurisdiction):

- **CFPB Circular 2022-03** — On credit decisions using complex algorithms, the Bureau affirms that **ECOA/Regulation B** still requires **specific, principal reasons** for adverse action; “black box” complexity is **not** an excuse for generic explanations. The circular is **credit-adverse-action** specific, but the *pattern*—outputs must be explainable to the affected party—is the same friction many fraud teams feel when a customer asks *why* and the vendor only offers a score band.  
  [consumerfinance.gov — Circular 2022-03](https://www.consumerfinance.gov/compliance/circulars/circular-2022-03-adverse-action-notification-requirements-in-connection-with-credit-decisions-based-on-complex-algorithms)

  *Legal scope (important):* This circular governs **credit adverse action** under **ECOA/Reg B**—not **payment fraud declines** or every checkout hold in the U.S. Cite it as an **analogy** for the *standard of explanation* you want in operations and customer care, **not** as a claim that the same statute applies to every fraud decision. Your counsel sets the actual regulatory perimeter.

- **Federal Reserve SR 11-7** (joint with OCC) — **Supervisory guidance on model risk management** for banking organizations: sound practices for **development, implementation, use, validation, and governance** of models whose outputs drive material decisions. When your “fraud rate” or vendor score is effectively a **production model**, this is the framework auditors and risk teams often reach for—especially for **third-party** models.  
  [federalreserve.gov — SR 11-7](https://www.federalreserve.gov/supervisionreg/srletters/sr1107.htm)

### Three anonymized shapes of failure (composite, not one company)

These are **archetypes** drawn from the kinds of cases practitioners describe in articles and talks—not court filings with names attached.

1. **The denominator moved.** A merchant celebrated a lower “fraud rate” until someone matched the vendor’s export to **internal labels** and realized the metric’s denominator had shifted with a product change. The model wasn’t magic; the story was.

2. **Silent calibration.** A payments team ran a **parallel holdout** and found score distributions had **drifted** after a backend update. No release note had mentioned it. Declines spiked for a corridor that looked “international” to the model and “core business” to the merchant.

3. **The VIP false positive.** Support escalated a blocked high-value user. The tool showed **high risk**. Nobody could cite **which signals** drove it. Engineering opened a ticket; the vendor’s answer took days. The customer was already gone.

If any of these feel familiar, the fix is rarely “find a smarter number.” It’s **definitions, drill-down, and change control**.

## Why vendors default to simple numbers (without calling them lazy)

Buyers often **ask** for simplicity. Sales cycles reward crisp ROI slides. Fine-grained exports raise **IP** worries (feature theft), **privacy** obligations (what leaves the boundary), **support load** (every dispute becomes a forensic request), and **UI** constraints (executives want one dial).

The problem is not that **summary metrics exist**. It’s when summaries are sold as **operationally and compliance-complete**—when “fraud rate” becomes the answer to *why this person*, not just *how did Q3 look*.

Good partnerships draw a line: **simplicity for the boardroom, accountability for the war room.**

## What to demand first: a tiered checklist

Smaller teams can’t swallow fifteen RFP demands on day one. Prioritize.

**Tier A — before you trust any headline metric**

- Written definitions of **fraud**, **attempt**, **decline**, and the **denominator** (e.g. approved transactions only vs all authorizations).
- **Lag policy**: how chargebacks and recoveries enter the metric; how partial data is handled.
- **Segmentation** at a minimum: new vs returning, channel, major geo or product line—so a shift in mix doesn’t masquerade as model quality.

**Tier B — before renewal or major volume commits**

- **Sample export** or API field set: score plus **top contributing factors**, even if **aggregated** or bucketed (not necessarily raw embeddings).
- **Versioning**: model or ruleset **ID** and **timestamp** attached to each score in production.
- **Change management**: notice window or release notes when scoring logic or default thresholds change customer-visible outcomes.
- Right to run **shadow scoring** or a **holdout slice** evaluated against **your** labels.

**Tier C — when false positives or regulatory scrutiny are expensive**

- **Calibration** reporting and dispute workflows tied to **signal-level** rationale (still subject to privacy redaction).
- Joint **evaluation** plan: label noise, chargeback lag, and survival bias explicitly documented.

## RFP and diligence questions you can paste

Use these verbatim or trim to fit procurement templates:

1. Provide the exact **formula and data sources** for each KPI in the executive dashboard.
2. What is the **latency** between a transaction and the **labels** (e.g. chargebacks) used in reported fraud rate?
3. Do production scores include a **model/ruleset version**? If not, what is the roadmap?
4. What **explainability** is available **at decision time** versus only in periodic reports?
5. Under what terms can we receive **pseudonymized or aggregated** attributions for disputes and internal tuning?
6. What **IP or confidentiality** clauses apply to exports, and what is the **minimum** transparency your contract will **guarantee** (not “best effort”)?

*None of this is legal advice.* Run contract language past counsel—especially across jurisdictions.

## Privacy, compliance, and the cost of “more data”

Asking for **richer** output is right; pretending it’s free is not. More fields mean **storage, retention, access control, and analyst time**. Start with signals that fit your **existing warehouse and case tool**, then expand when the **cost of false positives** justifies it.

On the legal side: prefer **hashed identifiers**, **aggregated cohorts**, **purpose-limited** exports, and **DPAs** that spell out subprocessors and retention. Raw user-level feature dumps can be toxic for **privacy programs** even when fraud teams mean well.

## Simple diagnostics your team can run quickly

You don’t need a research lab to sanity-check a vendor number:

- **Match-back:** Join a sample of scored transactions to **your** eventual outcomes (chargebacks, disputes, manual labels)—with realistic **lag windows**.
- **Short holdout:** Keep a slice on **parallel scoring** or stale thresholds; compare **stability** after vendor “maintenance” weekends.
- **Segment cut:** If the headline metric improved, check whether **one segment** (e.g. new users, one country) absorbed the change.

## For technical readers: a tiny reading list

If you want depth without turning the main article into a methods paper:

- Search **arXiv** / NeurIPS workshops for **fraud detection explainability**, **algorithmic transparency**, and **evaluation under label noise**.
- Pair **SR 11-7**-style governance with **FCA/BoE** discussion of AI/ML in financial services if you operate in the UK/EU (e.g. [FCA DP22-4 / AI & ML](https://www.fca.org.uk/publications/discussion-papers/dp22-4-artificial-intelligence) — context, not legal advice).
- **Internal discipline:** (1) **Calibration** — check that scores map to realized bad rates over time, with chargeback/dispute **lag** baked in. (2) **A/B or shadow** — compare policies on a defined slice, or run new logic in **shadow** before it touches customers. (3) **Selection bias** — remember you often have **rich labels only on some paths** (e.g. approved-then-chargeback, or manual review); don’t pretend declines and approvals are the same population for evaluation.

## Where an open stack fits (without forcing a product pitch)

Some teams will never get the transparency they need from a given contract. Others will negotiate something good enough. **Open-source, self-hosted** fraud stacks exist so **definitions, versions, and structured context** live in **your** repo and **your** VPC—`inference_context`-style payloads, versioned rules, and evaluation hooks as product behavior, not a professional-services upsell.

At **Tarka** we’re building for teams that decided **“prove it”** is non-negotiable: [github.com/pamu512/tarka](https://github.com/pamu512/tarka).

## Closing

Single-number fraud metrics are seductive. They’re also **compressions** of messy reality. Treat them that way: verify denominators, demand **minimum viable drill-down**, respect **vendor constraints** without accepting **operational blindness**, and budget the **ops and privacy** cost of richer data. Your customers—and your future self during the next 2 a.m. escalation—will know the difference.

---

**Suggested Medium topics:** Fraud Prevention, Fintech, Product Management, Data Science, Risk Management
