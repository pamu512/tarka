# 1. Record architecture decisions

Date: 2026-05-07

## Status

Accepted

## Context

Tarka spans many services, data stores, and deployment profiles. Without a single, versioned record of **why** the architecture looks the way it does, teams infer intent from code, Slack threads, and stale diagrams. That produces **environment drift**: staging and production diverge in undocumented ways, on-call assumes behavior that was never decided (only implemented), and new contributors ship changes that conflict with unstated constraints.

We already publish Markdown docs and OpenAPI contracts, but those formats optimize for **how to use** the system, not for **irreversible architectural choices** and their trade-offs.

## Decision

We adopt **Architecture Decision Records (ADRs)** as the source of truth for significant structural decisions.

1. **Location:** ADRs live under `docs/docs/adr/` in this repository (MkDocs section **ADRs**). New records are added as new Markdown files; existing files are amended only for clarifications, with the narrative preserved.
2. **Template:** We use the **Michael Nygard** shape for each ADR: **Title**, **Status**, **Context**, **Decision**, **Consequences**. Optional sections (e.g. **Alternatives considered**) are added when they materially affect trust or cost.
3. **Status values:** `Proposed` → `Accepted` | `Superseded` | `Deprecated`. Superseded ADRs link forward to the replacement ADR.
4. **Scope:** An ADR is appropriate when the choice is costly to reverse, affects security/compliance/auditability, spans multiple services, or defines a default that environments are expected to honor (so drift becomes detectable).

## Consequences

### Positive

- One canonical narrative per major decision; diffs are reviewable in Git like code.
- On-call and security reviews can cite ADR IDs instead of tribal knowledge.
- **Environment drift** is easier to detect: if an environment contradicts an accepted ADR, the gap is either a bug or a deliberate supersession (which must be recorded).

### Negative

- Authors must invest time writing context and consequences; lightweight “drive-by” docs are not ADRs.
- ADRs can go stale if supersession is not recorded; reviewers should treat “no ADR” as unknown intent, not permission.

### Neutral

- Operational runbooks and service READMEs remain the home for procedural detail; ADRs link to them where useful.
