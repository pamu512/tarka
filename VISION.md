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

## Hardware as moat

Local-first fraud detection was **economically irrational** on **DDR-limited, discrete-GPU, multi-socket** topologies: copying feature tensors and KV caches across buses dominated **time-to-decision**, and running **Gremlin + Postgres + LLM** on one box felt like a science project.

**Unified memory architectures**—especially **Apple Silicon** (M-series SoC, **CPU + GPU + Neural Engine + large memory pool on one die**)—change the unit economics:

- **Bandwidth:** Graph traversals, embedding-style work, and transformer inference **fight for the same memory pool** without PCIe-shaped choke points. For **interactive** fraud (sub-second policy + “explain this cluster”), **memory bandwidth is the product**.

- **Power envelope:** A **24 GB+** laptop-class machine can hold **model weights + working set + graph process** in a form factor banks already allow inside a **VPC DMZ** or secure room—no rack of A100s required for **first-line** agentic triage.

- **Deployment reality:** Tarka **1.3.0-beta** explicitly targets **M5 Pro class / 24 GB RAM** as the **full-stack** baseline (Gremlin-adjacent services, Ollama with Llama 3.2 / Qwen3-VL-class models, Rust core, orchestration). That is not snobbery—it is **physics**: local-first **without** unified memory is **pain**; with it, **local-first becomes default-competitive**.

**Moat thesis:** The next decade of fraud defense is won by teams who **co-design software for unified memory**—not who rent the most H100s in Virginia. Tarka is **optimized for that hardware regime** so **LFFI is viable for the first time at institution scale**, not only in labs.

---

## Conviction

We are not building a **better remote score**. We are building **infrastructure where intelligence and privacy stop trading off**—because **the model, the graph, and the rule engine share the same air-gapped room**.

**Prove every signal.** If it cannot be replayed, traversed, or cited from your own audit and graph edges, it does not ship.

---

*For stack wiring and beta install, see [`README.md`](README.md). For LFFI narrative and roadmap detail, see [`docs/LFFI_VISION.md`](docs/LFFI_VISION.md).*
