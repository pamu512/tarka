# Open-Core Boundary

This document defines what remains permanently OSS in Tarka and what is reserved for hosted/enterprise packaging.

## OSS Core (guaranteed)

- Decisioning and explainability:
  - `decision-api` evaluate path, rules, typologies, policy routing, inference context.
- Risk modules:
  - Counters + replay parity APIs/scripts.
  - Graph analytics and ring/mule heuristics.
  - ML scoring integration + drift endpoints.
  - External connector framework with Scameter adapter.
- Investigation + case operations:
  - Case evidence bundles, SAR support, investigation summaries.
- Deployment:
  - Local compose, OSS docs, and reference Helm/K8s manifests for self-hosting.

## Hosted / Enterprise Extensions (design boundary)

- Multi-tenant hosted control plane with SLO management.
- RBAC admin console for policy/config lifecycle and approvals.
- Managed connector marketplace with premium providers and operational SLAs.
- Trust Center dashboards that aggregate immutable records and compliance evidence.

## Packaging guardrails

- OSS services keep stable APIs and non-degraded behavior without enterprise components.
- Enterprise features are additive and deploy as separate services/packages.
- Core schema contracts (`contracts/openapi`, `contracts/golden`) stay open and versioned.
