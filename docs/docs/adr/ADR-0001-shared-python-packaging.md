# ADR-0001: Shared Python Packaging

- **Status:** Accepted
- **Date:** 2026-04-25

## Context

Multiple services previously relied on `sys.path` mutation and local path conventions to import shared modules. This made startup behavior fragile across local runs, tests, Docker, and CI.

## Decision

Adopt `services/shared` as the canonical shared Python package surface through explicit package exports (`tarka_shared.*`) and remove runtime `sys.path.insert(...)` path hacks from service/runtime code.

## Consequences

- Service imports are deterministic across local and containerized execution.
- CI can enforce import style consistency with a single gate.
- Shared utilities (auth, tracing, HTTP client, config validation) are reusable with stable import paths.
- New shared modules must be added under `tarka_shared` export surface to remain discoverable.

