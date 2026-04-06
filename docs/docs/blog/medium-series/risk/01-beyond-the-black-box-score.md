<!-- Subtitle: What auditors, customers, and your own team actually need to see -->

## The score is not the decision

If you’ve run fraud or risk operations for any length of time, you’ve seen this movie. A user gets blocked. Support opens a ticket. The vendor dashboard says **high risk** or shows a number. Someone asks *why*. The answer is a shrug, a PDF export, or a promise that “the model saw something.”

That might be fine for a marketing demo. It is not fine when a regulator asks what control failed, or when your best customer is on the phone asking what they did wrong.

We built **Tarka** around a simple idea: **a fraud decision should carry its homework**. Not a novel’s worth of text, but enough structured detail that a trained analyst (or a second system) can reconstruct the reasoning without a vendor bridge call.

## What “homework” looks like in practice

Picture three layers sitting next to each other after every check:

```
  Outcome          Evidence bundle           Short labels
  ---------        ----------------          ------------
  allow /          replay risk,              rule_hits,
  review /         network trust,            device tags,
  deny             geo consistency,          typology hints
                   velocity counts,
                   top contributing signals
```

The **outcome** is what product and support care about: did we let them through, hold them for review, or stop them?

The **evidence bundle** (we call it `inference_context` in the API) is what compliance and engineering care about: *what did we actually know at decision time?*

The **short labels** are what dashboards and queues care about: quick filters without parsing paragraphs.

When those three stay aligned, your case tool and your API consumer aren’t telling two different stories about the same person.

## Why this matters for false positives

False positives are unavoidable. **Unexplained** false positives are toxic. They burn support hours, train customers to work around you, and make it impossible to tune policy because nobody knows which knob turned.

If you can see that a block was driven mostly by velocity and a thin IP reputation, you can decide whether to widen a threshold, add a step-up path, or segment high-value accounts. If all you have is “model said no,” you’re guessing.

## Vendor vs. in-house (honest tradeoffs)

SaaS vendors can be fast to adopt. The recurring cost is opacity: you optimize what they expose, not what you understand.

Running software in your own environment (open source or otherwise) shifts work to your team: deployment, upgrades, monitoring. The upside is **you own the policy artifact**: rules, model versions, graph queries, and the audit trail that ties them to each decision.

Neither side is “winning.” The right question is whether your organization can **defend** the control, not whether the logo looks good on a slide.

Plenty of incumbents have gotten **serious** about explainability: **versioned** scores, **exportable** factors, **documented** KPIs. When your vendor already does that, the job is to **use** it—log every field you’re contractually allowed to have, tie it to **case IDs**, and hold renewals to that standard. If you’re stuck on a **score-only** API, **layer your own** correlation ID, timestamp, and any permitted reason payload so support isn’t arguing from memory.

## What to ask in your next tool review

Use this as a checklist in RFPs or architecture reviews:

1. **Can we export** the exact inputs and outputs for a decision at time *T*?
2. **Can we explain** a block without opening a support ticket with the vendor?
3. **Can we replay** a decision in a test environment with the same version of rules/models?
4. **Can we segregate** PII so shared intelligence doesn’t mean shipping raw customer data to a third party?
5. **Can we separate** “real-time block” from “investigation workflow” so one doesn’t freeze the other?

If the answer to several of these is no, budget time for incident response theater.

## Closing

Tarka is our attempt to make **proof** a first-class output, not a PDF afterthought. If you’re a risk owner, you don’t need to read our code to agree with the goal: **decisions your team can stand behind**. The implementation details are for your engineers; the standard of evidence is yours.

---

*Open source: [github.com/pamu512/tarka](https://github.com/pamu512/tarka)*
