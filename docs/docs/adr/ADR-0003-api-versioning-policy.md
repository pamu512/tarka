# ADR-0003: API Versioning Policy

- **Status:** Accepted
- **Date:** 2026-04-25

## Context

Tarka exposes many independently deployable services. Without explicit versioning policy, clients can be surprised by breaking changes.

## Decision

Adopt path-based major versioning (`/v1/...`) as the compatibility contract for service APIs. Major breaking changes require a new path version (`/v2/...`) with a migration window.

Additional rules:

- Backward-compatible additions are allowed within the same major version.
- Deprecated fields/endpoints must be documented before removal.
- CI/openapi checks should continue validating published API contracts.

## Consequences

- Client integrations have stable expectations tied to explicit major versions.
- Service teams can evolve APIs safely with clear migration milestones.
- Documentation must track deprecation and migration guidance per major version.

