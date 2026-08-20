# Tarka — Vision

**Category:** Local-First Fraud Intelligence (LFFI)

Privacy vs intelligence is a deployment choice: inference on metal you control.

---

## What Tarka is

Tarka is a **local-first fraud OS**. Two things define the product:

1. **Audit everything.** Every engine, rule, and AI decision has an audit trail. If a human changes the decision, we store *why* so the model can learn (`override → y_label`).

2. **Review is the exception.** Investigation is a residual station born from evaluate → deny / review. ALLOW never becomes a case. When review happens, there is a feedback loop back into the packs.

**Add-on:** omniscient AI (BYO LLM / scout) detects when a new rule is needed, writes it, parks it in canary / Observe, then auto-promotes or asks HIL when promote gates miss. Humans still own the live pack via gates.

---

## What Tarka is not

- Not a better remote score.
- Not a case-management CRM.
- Not a card / chargeback product.
- Not a Tarka-branded model.

---

## Journey, not payments

Progressive friction from signup onward: **login → device → onboarding → payment → payout**. At each hop: **allow / step-up / review / block**. Each event heats the next.

Skipping or avoiding a risk check does **not** block — it raises showing-signs risk.

Chargeback is one late label, not the product. Labels include dispositions, step-up outcomes, disputes, and other ground truth.

---

## Entity states

Do not flatten to a device flag.

| State | Meaning |
|-------|---------|
| **proven / already-risky** | Known good or known bad from prior evidence |
| **showing-signs** | Behavioral indicators accumulating |
| **unknown** | No signal yet |

Device is a node, not the person. ATO victims stay good.

---

## Selling point (vs Sardine / Unit21)

Owned JSON packs + native SDK evidence + in-tenant / VPC stack.

The demo beat is **"AI wrote this rule"** into Observe / canary — not a caption on `device_signals`, not a CRM ticket queue.

---

## Inference

**Production default** is a Linux VM + Compose desk: rules + audit on metal you control. See [SRE Compose profiles](docs/docs/operations/sre-compose-profiles.md).

**Graph (Janus)** is topological memory when wired — capable in repo, optional, not a day-1 requirement, not the minimum stack.

**Advise (LLM)** is optional forensics / copilot, BYO Azure OpenAI / Vertex / Bedrock / Claude / Qwen / in-cluster vLLM. In-tenant / VPC preferred; public internet APIs are not the enterprise default.

Colocating Gremlin + 30B + evaluate on one box is a **demo**, not the baseline.

---

## Evaluate stays Rust

`decision-api` owns allow / deny / flag / review. Rust JSON packs via `tarka_rule_engine`. No Tarka-branded model. No Python rule engine as canonical.

---

## Shadow naming

Do not collapse.

| Name | What it is |
|------|------------|
| **Observe** | Observe-only evaluate (`metadata.shadow`) + pack canary. RFP "shadow mode" = Observe only. |
| **Advise** | `shadow_agent` LLM, ops docs only. Hide Shadow chrome from lean. |

Never print "Shadow" as a third product on the desk.

---

## QA: two separate loops

1. **Blind predetermined-N evaluate events** so HIL confirms the engine. Schedulable; skip only if no drift.
2. **Second-human sample of cases already closed by HIL** (existing `qa_sample_closed_cases` / `/ops/qa`).

Do not collapse them.

---

## Conviction

**Prove every signal.** If it cannot be replayed, traversed, or cited from your own audit and graph edges, it does not ship.

We are not building a better remote score. We are building infrastructure where intelligence and privacy stop trading off — because the model, the graph, and the rule engine share the same air-gapped room when you choose that deployment.

---

*For stack wiring and beta install, see [`README.md`](README.md). For operator flows, see [`docs/INDEX.md`](docs/INDEX.md).*
