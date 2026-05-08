# 4. Envoy sidecar for transport concerns (retries, mTLS)

Date: 2026-05-08

## Status

Accepted

## Context

The **Rust rule engine** (`tarka-core` / `tarka_rule_engine`) is intentionally optimized for **deterministic rule evaluation**: verified rule bytes, bounded externals, reproducible evidence, and strict failure semantics. That surface is where security and audit reviewers spend their attention.

At the same time, every production deployment needs **transport-layer behavior** around RPC and HTTP calls to peer services and data planes:

- **TLS / mTLS** identity between workloads, rotation-friendly certificate handling, and ALPN/SNI correctness.
- **Retries with backoff and jitter**, hedging policies, timeouts, and circuit breaking so transient upstream faults do not collapse the engine process or leak ambiguous partial state into evaluation.
- **Observability hooks** (trace propagation, access logs, WAF-adjacent headers) that belong at the mesh edge rather than inside the evaluator’s hot path.

Those concerns can be implemented either **inside the engine** (as libraries linked into the Rust binary) or **outside** (as a **sidecar** process such as **Envoy** that terminates TLS and forwards plain or mTLS-protected traffic to localhost).

Embedding transport policy in the engine couples **two different rate-of-change surfaces**: fraud rules and cryptographic/network policy. It also expands the trusted computing base of the component whose outputs must replay bit-for-bit against audit evidence.

## Decision

We standardize on an **Envoy sidecar** (or equivalent mesh data plane) for **retries, timeouts, circuit breaking, and mTLS** on paths that originate from or terminate on services that host the Rust engine, rather than implementing those behaviors as first-class features inside `tarka-core`.

The Rust engine process should assume **stable, local, or already-authenticated** upstreams where practical (e.g. loopback to Envoy), and should remain **focused on rule execution**—parsing inputs, evaluating verified rules, emitting manifests—without owning enterprise-grade transport stacks.

Envoy is the **default reference** because it is widely deployed, has mature xDS configuration, and separates L7 policy from application code; teams may substitute another mesh proxy only if it meets the same operational bar (mTLS, bounded retries, structured telemetry) and is documented as a deliberate deviation.

## Consequences

### Positive

- **Smaller Rust attack and complexity surface** in the engine: fewer moving parts for auditors to map to evidence replay.
- **Uniform transport policy** across Python and Rust services behind the same sidecar contract (headers, retry budgets, TLS versions).
- **Independent rollout** of mesh upgrades vs engine releases, reducing coupling risk.

### Negative

- **Operational overhead** — sidecars consume memory/CPU; clusters must size pods accordingly and monitor Envoy config validity.
- **Two-hop debugging** — failures may require correlating engine logs with Envoy access logs and upstream health; runbooks must document that split.
- **Local dev parity** — developers need a documented way to run Envoy (or a slim equivalent) beside the engine, not only “engine binary only” for integration tests.

### Neutral

- **Application-level retries** inside Python services remain possible for idempotent orchestration; this ADR constrains **where transport-grade** retry/mTLS policy lives relative to the **Rust evaluator**, not every HTTP client in the fleet.
- Edge ingress (e.g. **Cloudflare, Kong**) may still terminate customer TLS; Envoy sidecars address **east-west** and service-to-service hardening called out in platform guides.
