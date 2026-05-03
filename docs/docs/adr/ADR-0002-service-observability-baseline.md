# ADR-0002: Service Observability Baseline

- **Status:** Accepted
- **Date:** 2026-04-25

## Context

Observability behavior diverged across services: some services emitted tracing context, others did not; startup auth-risk warnings were inconsistent.

## Decision

Standardize on a baseline for every service entrypoint:

1. `setup_observability(app, "<service-name>")`
2. `setup_tracing(app, "<service-name>")`
3. `log_runtime_warnings("<service-name>")` during startup/lifespan

## Consequences

- Request tracing headers propagate consistently across the platform.
- Startup logs surface insecure auth configuration risk in a uniform way.
- Incident debugging and cross-service correlation become simpler.
- New services must include this baseline before promotion to production environments.

