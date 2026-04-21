# Hosted Scaffolding (Year 1)

This directory contains minimal hosted deployment scaffolding for one-tenant pilots.

## Scope

- Baseline Kubernetes manifests for core API services.
- Environment-driven external services (managed Postgres/Redis, optional queue/warehouse).
- No control-plane/RBAC UI here; this is only workload scaffolding.
- Overlay entry points for `dev`, `staging`, `prod`, `aws`, and `gcp` under `deploy/hosted/k8s/overlays/`.

## Next steps

1. Add per-tenant namespace overlays (`kustomize`) on top of `overlays/prod`.
2. Add secret wiring through cloud secret managers and external secret operators.
3. Add ingress + mTLS policies and autoscaling policies per workload profile.
4. Add cluster policy and network policy guardrails by environment.
