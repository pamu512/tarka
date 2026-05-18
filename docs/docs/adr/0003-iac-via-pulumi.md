# 3. Infrastructure as code via Pulumi (Python)

Date: 2026-05-08

## Status

Accepted

## Context

Tarka’s runtime surface is predominantly **Python microservices** (FastAPI, workers, tooling) alongside Rust for the rule engine and performance-critical paths. Infrastructure for those services—Kubernetes objects, cloud IAM, data stores, queues, and observability wiring—must evolve **at the same cadence** as application code and be reviewable by the same engineers who own service behavior.

Traditional options each impose a **language boundary** between application and infrastructure:

- **Terraform (HCL)** is industry-standard but forces service authors to context-switch into a DSL with its own modules, testing story, and refactors that do not compose with Python packaging or CI patterns already used in this repo.
- **Vendor-native templates** (ARM/Bicep, CloudFormation-only) lock knowledge into a single cloud’s format and fragment expertise when the reference architecture spans multiple providers or abstractions (e.g. Helm + cloud primitives).
- **AWS CDK / CDKTF with TypeScript** aligns with a strong ecosystem but still leaves **most Tarka service engineers** translating between TS for infra and Python for services, duplicating dependency and review culture.

We want **one primary imperative language** for infrastructure logic where branching, reuse, policy checks, and unit tests feel familiar to the team that already ships Python.

## Decision

We adopt **Pulumi** for infrastructure as code, using the **Python** runtime (`pulumi` Python SDK) as the default language for new stacks and for extending existing ones unless a hard constraint requires otherwise (e.g. a third-party module only published for another language).

Rationale:

1. **Same language as microservices** — engineers who own APIs and batch jobs can own the **networking, identity, and data-plane** resources those jobs depend on without maintaining a parallel HCL/TS skill floor for routine changes.
2. **Composable programs, not only graphs** — Python packages, virtualenvs, type checkers, and linters already in CI apply to IaC the same way they apply to services, reducing “special snowflake” pipelines.
3. **Explicit escape hatches** — where a component is best expressed as YAML (Helm charts, CRDs), Pulumi can wrap it while keeping orchestration and environment wiring in Python.

This decision does **not** require rewriting every historical snippet overnight; it defines the **direction of travel** for net-new infrastructure and for refactors when touching a stack anyway.

## Consequences

### Positive

- **Lower cognitive load** for Python-first teams: reviews can treat infra changes like application PRs (imports, functions, tests) instead of a separate DSL-only workflow.
- **Shared tooling** — `pyproject.toml`, lockfiles, `mypy`/Ruff-style gates, and internal libraries can be reused or mirrored for infra projects where appropriate.
- **Faster onboarding** — new hires productive in Python can contribute to IaC earlier than if HCL or TS were mandatory for all layers.

### Negative

- **Operational coupling to Pulumi** — state backends, CLI versions, and provider upgrades become organizational commitments; mitigations include pinning provider SDK versions and documenting stack ownership.
- **Not the narrowest HCL footprint** — some third-party examples and modules are Terraform-first; teams may occasionally translate or wrap them.
- **Runtime discipline** — imperative IaC can hide side effects; we mitigate with **code review standards**, small modules, and automated previews (`pulumi preview`) as a required gate for material changes.

### Neutral

- **Rust-centric components** remain unchanged: Pulumi is chosen for **cloud and platform** automation, not to replace the Rust rule engine or performance-sensitive binaries.
- **Coexistence** — legacy Terraform or vendor templates may remain until replaced; this ADR governs **preferred** tooling for new work, not a big-bang migration deadline.
