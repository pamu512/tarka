# Tarka — Vision

**Project:** Tarka 1.3.0-beta  
**Category:** Local-First Fraud Intelligence (LFFI)

---

## The privacy–intelligence paradox

Fraud is a **reasoning problem** dressed up as a **data problem**.

The industry built itself around a contradiction: **high-quality intelligence**—the kind that needs rich context, sequence, and now LLM-grade synthesis—**wants data in one place**, usually someone else’s cloud. **High-quality privacy**—GDPR-class minimization, residency, and defensible DPAs—**wants data fragmented, local, and provably contained**.

Pick intelligence, and you bleed **PII across borders** into multi-tenant SaaS. Pick privacy, and you retreat to **brittle rules and shallow velocity** because nobody will ship the full transaction graph and chargeback PDFs to a vendor API.

**That paradox is not a law of physics. It is a deployment choice.**

Tarka resolves it by **moving inference gravity to the edge**: the same graph and audit trail your bank already owns, **reasoned over by models that never leave silicon you control** when you run Shadow on local inference (e.g. Ollama on-loopback). You trade **capital expense (RAM, unified memory, ops)** for **strategic optionality (no mandatory PII export for “smart” fraud)**.

---

## The Tarka Triad

Three layers, three different failure modes if any one is missing. Together they are the minimum credible stack for **post-black-box** fraud.

| Pillar | Role | One-line job |
|--------|------|----------------|
| **Rust — Speed** | Deterministic **first response** | Turn policy into **bytes you can replay**: same inputs → same outputs, manifests, `tarka replay`, WASM leaves where configured. This is **speed as auditability**—not speed as “hide the model.” |
| **JanusGraph — Context** | **Topological memory** | Transactions are not rows; they are **vertices and edges** in an evolving graph. **Context** is who touched which device, which IP, which listing—**multi-hop**, not a single feature vector refreshed nightly. |
| **Shadow AI — Reasoning** | **Forensic synthesis** | Turn graph signals + policy payloads into **structured, citeable narratives** for analysts and downstream case systems. **Reasoning** here means: hypotheses **grounded in graph context**, not a lone score from a black box. |

Rust answers “what does policy **mandate**?”  
JanusGraph answers “what **relationships** exist?”  
Shadow answers “what **story** does an investigator need to act?”

Strip one leg, and you get either **un-auditable ML**, **context-free rules**, or **graphs nobody can explain**.

---

## The market gap

Incumbent **cloud fraud APIs** (e.g. **Sift**, **Forter**, and the same architectural class) won the last decade by centralizing **signals + models + ops**. That centralization collides with three structural shifts:

1. **Regulation and procurement** — GDPR, UK GDPR, emerging state laws, and bank-grade DPAs increasingly treat **cross-border enrichment of raw transaction payloads** as a **negotiation**, not a checkbox. “Send us everything, we return a score” is under pressure **even when vendors are competent**.

2. **LLM economics** — **General reasoning** is now cheap enough to run **locally** on unified-memory machines. The old excuse—“only the hyperscaler can afford the model”—is weaker every hardware generation. The bottleneck moves from **GPU capex** to **architecture**: can your stack **co-locate** graph, rules, and inference without shipping PII?

3. **Adversarial maturity** — Coordinated abuse is **graph-native** (rings, mules, device farms). Row-scoring vendors bolt on **graph features**; Tarka assumes **the graph is the system of record for coordination**, not an optional enrichment pipe.

**Gap statement:** The market still sells **“trust our cloud brain.”** Tarka sells **“trust your own edges, receipts, and Gremlin traversals.”** That is not a feature delta—it is a **different category**: **LFFI**.

---

## Where inference runs

**Production default** is a Linux VM and Compose **desk** profile: rules + audit on metal you control. See [SRE compose runbooks](docs/docs/operations/sre-compose-profiles.md).

**Local Shadow** (Ollama on-loopback) is an **optional forensics** add-on so cluster narratives need not leave the VPC. That is a residency choice, not a laptop SKU requirement. Graph and large local weights belong on separate hosts from evaluate.

Colocating Gremlin + a 30B-class model + evaluate on one box is a **demo**, not the baseline.

---

## Conviction

We are not building a **better remote score**. We are building **infrastructure where intelligence and privacy stop trading off**—because **the model, the graph, and the rule engine share the same air-gapped room**.

**Prove every signal.** If it cannot be replayed, traversed, or cited from your own audit and graph edges, it does not ship.

---

*For stack wiring and beta install, see [`README.md`](README.md). For operator flows, see [`docs/INDEX.md`](docs/INDEX.md).*
