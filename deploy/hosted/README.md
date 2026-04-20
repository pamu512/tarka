# Hosted Scaffolding (Year 1)

This directory contains minimal hosted deployment scaffolding for one-tenant pilots.

## Scope

- Baseline Kubernetes manifests for core API services.
- Environment-driven external services (managed Postgres/Redis, optional queue/warehouse).
- No control-plane/RBAC UI here; this is only workload scaffolding.

## Next steps

1. Add per-tenant namespace overlays (`kustomize`).
2. Add secret wiring through cloud secret managers.
3. Add ingress + mTLS policies and autoscaling.
