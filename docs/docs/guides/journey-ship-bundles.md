# Pending ships rebundled by user journey

This guide **re-slices** planned work (30/60/90, `v1.2.0` / `v1.3.0` release notes, and OSS issues **`#31`–`#54`**) around **who does what**, not around repos. Use it to plan **cohesive trains**: each cut should advance **at least one journey** end-to-end (thin vertical slice) where possible.

**Does not replace** the technical DAG in [oss-ship-order-dependencies.md](./oss-ship-order-dependencies.md)—that file still defines **must-do-before** edges. This file defines **why** those edges exist in product terms and **which journeys** each pending item serves.

---

## Journeys (primary actors)

| Journey | Actor | Job-to-be-done |
|--------|--------|----------------|
| **J1 — Integrate** | Integrations / backend engineer | Ingest reliable events, device/session integrity, connector health. |
| **J2 — Decide** | Risk engineer / automation | Score, rule, shadow/canary, promote policy safely. |
| **J3 — Investigate** | Fraud analyst | Triage case, explain decision, graph/velocity context, experiments, drafts. |
| **J4 — Govern** | Compliance / security / leadership | Trust posture, evidence for audits, release discipline. |
| **J5 — Operate** | SRE / platform | Degraded modes, observability, SLAs, runbooks. |

Cross-cutting: **SDKs + OpenAPI** serve **J1–J3**; **deployment profiles** serve **J3–J5** (honest UX and ops).

---

## J1 — Integrate (ingestion & connector quality)

**Outcome:** Producers send a **stable envelope**; ingress is **observable and truthful** when connectors fail.

| Pending ship | Source | Journey note |
|--------------|--------|----------------|
| SDK envelope / guards / mobile attestation taxonomy | OSS **#43, #44, #45** | Normalized fields before shadow/canary routing is meaningful. |
| Connector quality + probes | OSS **#54** | Treat probes as **steps** (aligns with **#32**). |
| Integration ingress reliability / SLA surfaces | Roadmap **v1.2** (ingress panel); Epic **connector reliability** | Same story as **#54**—one “integration health” narrative. |
| Pipeline step controls | OSS **#32** | Unifies timeout/retry/`onFailure` for probes and downstream steps. |

**Cohesive bundle to aim for:** *“Ingress profile X documents which fields are required; SDKs send them; probes prove connector health; UI shows degraded state.”*

---

## J2 — Decide (policy, experiments, promotion)

**Outcome:** Champions/challengers, typologies, and promotion **don’t lie**; experiments have **guardrails**.

| Pending ship | Source | Journey note |
|--------------|--------|----------------|
| Policy DAG shadow / champion-challenger | OSS **#31** | Core routing; depends on **#32** step contract. |
| Canary cohort audit fields | OSS **#47** | Audit explains **which cohort** saw which path. |
| Model promotion gates | OSS **#37**; **v1.2** preset profiles | One governance story: **gates + YAML + CI**. |
| Promotion policy YAML + CI | OSS **#52** | Implements **#37** in repo automation. |
| Typology layer + DSL registry + starter packs | OSS **#34, #46, #39** | Rule authors and vertical packs share **typology IDs**. |
| Velocity counters + parity verifier | OSS **#33, #48** | Trustworthy counters for rules and benchmarks. |
| Simulation / benchmark harness | **v1.2**; OSS **#41** (scorecards path) | **v0** can lean on replay/synthetic; **full** scorecards after **#48** when claiming counter parity. |
| Parity verifier job | OSS **#48** | Certifies **#33** before “official” benchmark claims. |
| Experiment guardrails (existing + deeper) | **v1.1** simulation; roadmap depth | Keeps **J2** from misleading risk owners. |

**Cohesive bundle to aim for:** *“One tenant runs shadow DAG + canary metadata in audit; promotion YAML blocks bad merges; typology pack references stable IDs; benchmarks document parity status.”*

---

## J3 — Investigate (analyst loop)

**Outcome:** From **queue → explain → graph/velocity → optional replay/labels → export narrative**, without jumping between unrelated backlogs.

| Pending ship | Source | Journey note |
|--------------|--------|----------------|
| Case investigation workflows | OSS **#35** | Structured steps/failures (**#32**) + audit consistency. |
| Investigation agent summaries | OSS **#40** | Should consume **evidence bundle** shape (**#50**) when stable. |
| Evidence bundle schema v1 | OSS **#50** | Unifies case export, agent output, Trust Center evidence. |
| Frontend mode UX + readiness banner | OSS **#36, #51**; **#38** profiles | Analyst sees **honest** detection vs compliance / degraded state. |
| Graph checkpoint registry + selective routing | OSS **#49, #42** | Faster/safer graph work in investigations. |
| Drivers / explainability / Case Detail (ongoing) | Epic **F**, **v1.1** baseline | Foundation for **#40** and **#50**. |

**Cohesive bundle to aim for:** *“Case detail shows drivers + recommended action; agent tools match audit/trace APIs; label drafts and replay A/B share tenant+analyst semantics; evidence refs align with bundle schema v1.”*

---

## J4 — Govern (trust, audit, procurement)

**Outcome:** **Controls and evidence** are exportable and tied to releases—not a separate documentation project.

| Pending ship | Source | Journey note |
|--------------|--------|----------------|
| Trust Center UI | **v1.3** | Surfaces health, controls, runbook links—**same profile semantics** as **#36/#51**. |
| Evidence export APIs | **v1.3**; decision + case roadmap | Feeds **#50** bundle and procurement. |
| Release governance checklist + CI | **v1.3** | Blocks “silent” breaking posture changes. |
| Signed release artifacts | **v1.3** | Procurement-grade reproducibility. |
| Enterprise proof kit / control matrix (docs) | **v1.3** roadmap | Maps **J4** artifacts to buyer questions. |

**Cohesive bundle to aim for:** *“Trust Center fields = OpenAPI contracts; exports include typology/rule/promotion version; CI gate = documented checklist; signed bundle per tag.”*

---

## J5 — Operate (SRE / platform)

**Outcome:** Operators know **profile**, **degradation**, and **blast radius** without reading every service README.

| Pending ship | Source | Journey note |
|--------------|--------|----------------|
| Deployment profiles docs | OSS **#38** | **Prerequisite** for honest mode UX (**#36, #51**) and Trust Center. |
| Automated scorecards | OSS **#41** | Ops + risk visibility; **#53** publishes to Discussions. |
| Scorecard → Discussions | OSS **#53** | Weekly narrative for OSS adopters. |
| Deeper challenge orchestration + ingress SLA (from roadmap) | **v1.2** | Links **J5** alerts to **J1** connector state. |

**Cohesive bundle to aim for:** *“Profile doc → env vars → dashboard/banner → runbook link” is one numbered run.**

---

## How to use this with releases

- **v1.2.0** (per [v1.2.0-2026-05-30.md](../releases/v1.2.0-2026-05-30.md)) is naturally **J2** (packs, benchmarks, presets) + **J1** (ingress reliability) + **J5** (scorecards path). Tag each PR with **J1–J5** in addition to component.
- **v1.3.0** (per [v1.3.0-2026-06-29.md](../releases/v1.3.0-2026-06-29.md)) is **J4**-heavy; pull **#50** and **#38** in early so Trust Center is not a greenfield schema.

## Minimal cross-journey spine (thin vertical)

If you must ship one slice that touches every journey:

1. **#38** profile doc names one **staging** profile.  
2. **#43–#45** send one new **envelope field** used in evaluate.  
3. **#32** records one **step** for a connector probe (**#54**).  
4. **Audit** (**#47** when ready) stores cohort/step id for that path.  
5. **Case Detail / agent** reads the same audit fields (**J3**).  
6. **Trust Center** documents that profile (**J4**) and links runbook (**J5**).

---

## Related docs

- [OSS adoption backlog DAG](./oss-ship-order-dependencies.md) — merge order and edges.  
- [30/60/90 roadmap](./roadmap-30-60-90.md) — dates and epic alignment.  
- [Service ports & OpenAPI index](./service-ports.md) — default ports and contract locations for cross-journey slices.  
- [Module projects](../projects/README.md) — service-level detail; link each **Next** item to a **J1–J5** label when updating.  
- [Competitive critical review (2026-04)](./competitive-critical-review-2026-04.md) — buyer-facing gaps this mapping targets.
