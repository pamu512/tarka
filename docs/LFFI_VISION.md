# Local-First Fraud Intelligence (LFFI)

**Project:** Tarka **1.3.0-beta**  
**Author:** Solo founder strategy (product + architecture narrative)

This document states **why** the stack is shaped the way it is. For wire-level behavior, see [`SYSTEM_DESIGN.md`](SYSTEM_DESIGN.md) and the repo [`README.md`](../README.md).

---

## Vision: The end of “black box” fraud detection

Most production systems give you one of two bad options: **opaque model scores** you cannot defend in an audit, or **brittle rules** you cannot extend to coordinated abuse. Tarka’s bet is that **evidence-grade** output requires **three** legible layers—deterministic policy, **mutable graph memory**, and **local** agentic explanation—so nothing that matters is “trust us, it’s ML in region us-east-1.”

---

## 1. Core thesis: The privacy–intelligence paradox

Today’s fraud stack is squeezed by a real constraint:

- **Strong intelligence** (large models, rich context) historically pushed **PII and payloads toward vendor APIs**.
- **Strong privacy** (data never leaves the VPC) historically pushed teams toward **dumb** velocity flags and static rules.

**LFFI** resolves that by moving **inference gravity to the edge**: high-throughput Apple Silicon (e.g. **M5 Pro** class) and containerized sidecars run **Shadow** over the **same graph and audit rows** you already committed—**no packet of raw PII has to leave the host** when you keep models local (Ollama on-loopback is the default posture in beta docs).

You do not get “free” privacy: you pay in **RAM, GPU-class SoC, and ops discipline**. You get **defensible** intelligence.

---

## 2. Architectural moat: Topological reasoning

**Rows lie about coordination.** **Edges do not**—if you wrote them honestly.

| Layer | Role | What it is good at |
|--------|------|---------------------|
| **Rule engine (Rust / `tarka-core`)** | First line of defense | **Known knowns**—policies with deterministic replay (`tarka replay`), WASM hooks where configured, auditable manifests. |
| **Graph (JanusGraph, Gremlin)** | System memory | **Known unknowns** as **structure**—shared devices, IP neighborhoods, multi-hop paths, review-ring topology. Velocity of **connections**, not just scalar velocity. |
| **Agent (Shadow AI)** | Forensic scientist | **Unknown unknowns** as **hypotheses grounded in graph context**—why this **cluster** of fifty accounts behaves like a Sybil ring, citing topology the analyst can re-walk—not a lone score. |

Tarka **1.3.0-beta** ships the seams: ingest → rules → optional graph materialization → optional Shadow with **AuditLog** as the write-ahead for automated disposition.

---

## 3. The shift: From “event” to “identity”

Legacy rails are **transaction-centric**: “Is *this payment* fraud?”

Tarka is **identity- and network-centric**: “Is *this identity* sitting inside a **hostile subgraph**?”

JanusGraph is how you make that question operational: when a **device** vertex suddenly gains **five new email** edges in ten minutes, the **topology** changes—not just a counter field. That change can **trip rule thresholds** and/or **invoke Shadow** with graph-enriched prompts so the operator sees **why** the cluster matters, not only **that** a model disagreed with a rule.

---

## 4. Product roadmap: The fraud OS (beyond 1.3.0-beta)

**1.3.0-beta** is the **foundation**: ingest contract, Rust determinism at the core, graph sidecar path, local Shadow, Next.js operator UI with the **Knowledge Drop Zone** (document priming into investigations).

**Forward-looking** (not all shipped in-tree today; this is the build order we care about):

1. **Autonomous dispute resolution** — Chargeback PDFs and evidence packets enter via the Knowledge Drop Zone; **graph-backed** facts cross-reference into **representment** drafts with human sign-off, not magic auto-send.
2. **Federated graph intelligence** — Separate Tarka deployments exchange **anonymized risk signatures** (e.g. hashes of cluster fingerprints / rule manifests)—**not** raw PII—so institutions can align on **syndicated abuse patterns** without a central data lake of customer secrets.
3. **Zero-knowledge fraud proofs (research)** — Cryptographic goal: prove to a third party that a decision met policy **without** revealing underlying identifiers. Tarka’s **auditable edges + manifests** are the substrate you would eventually prove over; this line item is **not** a shipped product claim in beta.

---

## Operating principle

**Prove every signal.** If the graph, the rule bundle, and the audit row cannot support the story, the story does not ship.
