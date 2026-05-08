# 5. Scaling roadmap: Platform and Feature squads (~20 engineers)

Date: 2026-05-08

## Status

Accepted

## Context

As engineering grows toward roughly **20 people**, coordination costs rise faster than headcount if every change touches the same surfaces: developer environments, cloud provisioning, edge routing, and observability. Without intentional boundaries, teams either **serialize on one platform backlog** or **fork infrastructure per feature**, which invites drift and eventually pressures a “rewrite the core” reaction.

Tarka already commits to four complementary layers that are **orthogonal to fraud-domain logic**:

1. **Nix** — reproducible local and CI environments (flake, process-compose, dev shells).
2. **Pulumi** — imperative infrastructure as code aligned with the Python service stack (see ADR 0003).
3. **OpenTelemetry** — standardized traces, metrics, and logs with export paths into durable stores (for example ClickHouse for forensic traces, aligned with collector configs in-repo).
4. **Envoy** — edge and mesh-adjacent concerns: ingress, retries, timeouts, TLS/mTLS, and access logging without embedding those policies in every service (see ADR 0004).

The question is not whether to adopt these tools (they are already directionally chosen) but how they **enable org design**: splitting ownership into **Platform** and **Feature** squads while keeping a single core codebase and evolution path.

## Decision

We organize scaling around **contracts at boundaries**, not around rewriting the rule engine or merging unrelated domains into one team.

### Squad split (intent)

| Concern | Primary owner (“Platform”) | Primary owner (“Feature”) |
|--------|------------------------------|---------------------------|
| Flake hygiene, devshell defaults, local dependency matrices (Postgres, Redis, ClickHouse, Loki, etc.) | Owns | Consumes; proposes changes via PR |
| Pulumi stacks: VPC, IAM, databases, queues, cluster primitives, shared observability plumbing | Owns shared stacks | Owns **application-level** config only where isolated stacks exist (document per service) |
| OTel collector configs, baseline exporters, trace retention alignment with audit needs | Owns | Instruments services (SDK usage, span attributes, structured logs); owns domain semantics |
| Envoy bootstrap, listeners, cluster defs, retry budgets, cert mounts for sidecars | Owns templates | Owns HTTP handlers behind stable upstream names; does not fork Envoy per feature |
| Rust rule engine, evidence manifests, core APIs | Shared ownership / Architecture council | Ships vertical features **through** those APIs and extension points |

**Feature squads** deliver tenant-facing or domain workflows (rules packs, case workflows, integrations, analyst UX) and ship services that **assume** stable ingress (Envoy), stable deployment knobs (Pulumi outputs), and stable telemetry contracts (OTel). **Platform** squads deliver **repeatable environments and fleet-wide policies** so Feature squads do not re-solve TLS, tracing export, or “why does my laptop differ from prod?”

This ADR does **not** mandate a formal re-org date; it records **how existing infrastructure choices support** that split when you choose to execute it.

### Why the core does not need rewriting

- **Nix** pins **toolchains and local topology** (what runs on `localhost`, which ports, which helper processes). Feature work consumes the same shells; changes roll out as flake updates rather than “install this brew tap.” That keeps the **Rust engine and Python services** on one upgrade train without a monolithic platform gate for every product tweak.

- **Pulumi** keeps **cloud shape** in versioned Python programs with previews. Platform can evolve VPC, RDS, ClickHouse, NATS, or collector sidecars; Feature teams consume outputs (URLs, secrets references, subnets) as **stack outputs** or thin wrappers. Domain logic stays in application repos; **fleet topology** stays in IaC—so you scale infrastructure reviewers separately from fraud-rule reviewers.

- **OpenTelemetry** separates **instrumentation** (every service adds spans and labels) from **aggregation** (collectors, backends, retention). Feature squads own **business attributes** on spans and logs; Platform owns **pipelines** so forensic queries and SLO dashboards stay coherent as services multiply.

- **Envoy** centralizes **north–south and east–west policy** (timeouts, retries, mTLS termination, access logs). Services remain plain HTTP/gRPC behind upstream clusters; scaling out Feature teams does not imply **N copies** of retry logic or TLS parsing in FastAPI.

Together, these layers mean new engineers can join a **Feature** squad and ship vertical value behind **stable contracts**, while Platform evolves the **fleet** without opening the Merkle tree or rule compiler for every infra tweak.

## Consequences

### Positive

- **Clear review lanes**: flake/process-compose changes versus Pulumi stack changes versus Envoy YAML versus product APIs reduce accidental coupling in PR discussion.
- **Parallel throughput**: Feature squads ship domain milestones while Platform lands collector upgrades or mesh cert rotation with fewer cross-dependencies.
- **Onboarding paths**: junior engineers can start in Feature with domain tests and OTel conventions; Platform provides runbooks for shells and deploy previews.

### Negative

- **Contract discipline**: boundary APIs (stack outputs, listener names, required span attributes) must be **documented and versioned**; informal “just SSH and fix” erodes the model.
- **Platform staffing**: without at least partial allocation to Nix/Pulumi/Envoy/OTel ownership, Feature teams will recreate partial duplicates (custom compose files, ad hoc dashboards).

### Neutral

- **Monorepo can persist**: squad boundaries are **ownership and CI paths**, not mandatory repository splits. Splitting repos later remains optional if boundaries stay clean.
- **ADR 0002 (“infrastructure for proof”)** remains the philosophical anchor: scaling reinforces **evidence-grade operations**, not velocity at the expense of auditability.

## References

- ADR 0001 — Record architecture decisions  
- ADR 0002 — Infrastructure for proof philosophy  
- ADR 0003 — IaC via Pulumi (Python)  
- ADR 0004 — Envoy sidecar (retries, mTLS)
