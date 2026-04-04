# Python SDK Project

## Scope

Server-side integration client, typed contracts, signal helpers, and backend framework ergonomics.

## Current Gaps

- Typed response contracts were improved but need broader endpoint typing.
- Error taxonomy and retry guidance need stronger production defaults.

## Roadmap

### Now

- Keep API contract parity with decision response inference fields.
- Add stricter typed dict coverage across critical methods.

### Next

- Add normalized SDK error classes with retry semantics.
- Improve connection reuse/lifecycle patterns for high-throughput workloads.

### Later

- Auto-generated typed client from OpenAPI with compatibility checks.
